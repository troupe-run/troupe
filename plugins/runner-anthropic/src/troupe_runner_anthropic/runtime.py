"""The run's runtime: the service the runner talks to (spec: anthropic-runner, "The service comes
from the run's runtime"; anthropic-runner design D3, D4).

The runtime's endpoint, model and credential come from troupe (#278), never from the runner's
options. run/start carries the runtime as troupe resolved it, and the credential's value is in the
runner's environment as TROUPE_RUNTIME_CREDENTIAL (spec: runner-protocol). This module is the one
place the runner reads the runtime. It parses the endpoint with urllib.parse, which does no I/O.
"""

import ipaddress
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field

from troupe_plugin_sdk.credential import (
    CREDENTIAL_VARIABLE,
    CredentialError,
    runtime_credential,
    well_formed,
)
from troupe_plugin_sdk.runner import Price, RunStartParams

MESSAGES_PATH = "/v1/messages"
"""Where the library sends each request, below the runtime's endpoint."""


class RuntimeRefusedError(Exception):
    """A runtime refused, with the code, the problem, the fix and its details."""

    def __init__(self, code: str, problem: str, fix: str, details: dict[str, str]) -> None:
        super().__init__(problem)
        self.code = code
        self.problem = problem
        self.fix = fix
        self.details = details


def is_loopback(host: str) -> bool:
    """Whether ``host`` is this machine: ``localhost`` or a loopback address. A name that merely
    starts like one (127.0.0.1.example.com) isn't."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Endpoint:
    """A runtime's endpoint: the Messages API's base URL, below which the library adds
    /v1/messages, such as https://api.anthropic.com or http://127.0.0.1:1234."""

    url: str
    """As the runtime gives it, without a trailing /."""
    scheme: str
    host: str

    @property
    def messages_url(self) -> str:
        """Where each request goes."""
        return self.url + MESSAGES_PATH

    def is_insecure_for(self, has_credential: bool) -> bool:
        """Whether sending a credential here would send it in the clear to another machine."""
        return has_credential and self.scheme == "http" and not is_loopback(self.host)


def _refused(problem: str, fix: str) -> RuntimeRefusedError:
    return RuntimeRefusedError(
        "anthropic.unsupported-endpoint", problem, fix, {"where": "runtime.endpoint"}
    )


def parse_endpoint(text: str) -> Endpoint:
    """``text`` as an Endpoint, or RuntimeRefusedError naming what's wrong, never repeating an
    endpoint that may hold user info (runtime-checks design D8, #323).

    A path ending in /v1 is refused, naming the base without it: it's the OpenAI-style base copied
    across, and the library would send requests to /v1/v1/messages (design D3)."""
    shown = "The endpoint (not shown: it may hold user info)" if "@" in text else repr(text)
    try:
        parts = urllib.parse.urlsplit(text)
        host = parts.hostname or ""
        parts.port  # noqa: B018 - raises ValueError for a port that isn't a number in range
    except ValueError:
        raise _refused(
            f"{shown} isn't a URL with a host and a port in range.",
            "Give the runtime the Messages API's base URL, such as https://api.anthropic.com.",
        ) from None
    if parts.username or parts.password:
        raise _refused(
            "The runtime's endpoint has a user name or password, which an endpoint never holds; "
            "it isn't shown.",
            "Give the runtime the endpoint alone, and its key through credential.env.",
        )
    if parts.scheme not in ("http", "https") or not host:
        raise _refused(
            f"{shown} isn't an http or https URL with a host.",
            "Give the runtime the Messages API's base URL, such as https://api.anthropic.com.",
        )
    # An empty query or fragment ("…?" or "…#") is still one: urlsplit gives "" for it, but the
    # text keeps the ? or #, which would land in front of /v1/messages. User info, which may hold
    # either, was refused above.
    if parts.query or parts.fragment or "?" in text or "#" in text:
        raise _refused(
            f"{shown} has a query or fragment, which the library would drop or garble: an "
            "endpoint is a base URL only.",
            "Give the runtime the endpoint without its query or fragment.",
        )
    base = text.removesuffix("/")
    path = parts.path.removesuffix("/")
    if path.endswith("/v1"):
        root = base.removesuffix("/v1")
        raise _refused(
            f"The runtime's endpoint, {base}, ends in /v1, but the Messages API's library adds "
            f"{MESSAGES_PATH} itself, so requests would go to {base}{MESSAGES_PATH}.",
            f"Give the runtime the base without /v1: {root}.",
        )
    return Endpoint(base, parts.scheme, host)


@dataclass(frozen=True)
class Runtime:
    """The service one run talks to. The credential never shows in its repr."""

    endpoint: Endpoint
    model: str
    credential: str | None = field(default=None, repr=False)
    price: Price | None = None
    """The model's price troupe gave in run/start, the only one the runner may estimate a cost
    from; None when the theatre doesn't price the model."""

    @classmethod
    def checked(
        cls, endpoint: str | None, model: str, credential: str | None, price: Price | None = None
    ) -> "Runtime":
        """A Runtime from its parts, refused when there's no endpoint (an in-process runtime), the
        endpoint can't be used, the model is empty, the credential is malformed, or it would go in
        the clear to another machine."""
        if endpoint is None:
            # An in-process runtime, which config wouldn't let an Anthropic actor name
            # (in-process-runner design D5).
            raise RuntimeRefusedError(
                "anthropic.no-runtime",
                "The runtime has no endpoint: it's in-process, for a runner that loads its model "
                "itself, and the Anthropic runner talks to a service at an endpoint.",
                "Name a runtime with an endpoint for the actor, such as the built-in anthropic.",
                {"where": "runtime.endpoint"},
            )
        parsed = parse_endpoint(endpoint)
        if not model:
            raise RuntimeRefusedError(
                "anthropic.no-runtime",
                "The runtime names no model.",
                "Give the actor or its runtime the model its service should run.",
                {"where": "runtime.model"},
            )
        credential = credential or None
        if credential is not None and not well_formed(credential):
            raise RuntimeRefusedError(
                "anthropic.malformed-credential",
                f"The run's credential in {CREDENTIAL_VARIABLE} holds a character a request header "
                "can't carry, such as a space, a line ending left from the file it was read from, "
                "or a letter outside ASCII.",
                "Set the runtime's key variable to the key alone: only visible ASCII characters, "
                "with no spaces or line endings.",
                {"where": CREDENTIAL_VARIABLE},
            )
        if parsed.is_insecure_for(credential is not None):
            raise RuntimeRefusedError(
                "anthropic.insecure-endpoint",
                f"The runtime's endpoint {parsed.url} is plain http to another machine, so its "
                "credential would travel in the clear.",
                "Use the service's https endpoint. Plain http is only for a server on this "
                "machine (localhost or a loopback address).",
                {"endpoint": parsed.url},
            )
        return cls(parsed, model, credential, price)


def from_run_start(params: RunStartParams, environ: Mapping[str, str]) -> Runtime:
    """The run's runtime: run/start's, with its credential from ``environ``. Refused when there's
    no runtime, when run/start and ``environ`` disagree about the credential, and as
    Runtime.checked refuses."""
    if params.runtime is None:
        raise RuntimeRefusedError(
            "anthropic.no-runtime",
            "run/start names no runtime, so the Anthropic runner has no service to talk to.",
            "Name a runtime for the actor, such as troupe config set "
            "actors.<name>.runtime=anthropic.",
            {"where": "runtime"},
        )
    try:
        credential = runtime_credential(params, environ)
    except CredentialError as error:
        raise RuntimeRefusedError(
            "anthropic.credential-mismatch",
            f"{error}, so the runner can't tell whether to send a credential.",
            "troupe sets the variable exactly when run/start says the runtime has a credential; "
            "start the runner through troupe, or report the mismatch.",
            {"where": CREDENTIAL_VARIABLE},
        ) from None
    return Runtime.checked(
        params.runtime.endpoint, params.runtime.model, credential, params.runtime.price
    )


__all__ = [
    "MESSAGES_PATH",
    "Endpoint",
    "Runtime",
    "RuntimeRefusedError",
    "from_run_start",
    "is_loopback",
    "parse_endpoint",
]
