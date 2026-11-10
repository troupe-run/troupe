"""The run's runtime: the LM Studio the runner talks to (spec: lm-studio-runner, "The service comes
from the run's runtime"; lmstudio-runner design D3, D4).

The runtime's endpoint and model come from troupe (#278), never from the runner's options. The
endpoint becomes the library's host and port, always given, so the library never looks for LM Studio
on ports of its own. LM Studio's library speaks only plain ws:// and can't send an API token, so an
https endpoint and a runtime with a credential are refused rather than sent without what they ask
for. This module is the one place the runner reads the runtime.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

from troupe_plugin_sdk.credential import CREDENTIAL_VARIABLE
from troupe_plugin_sdk.runner import Price, RunStartParams

DEFAULT_HTTP_PORT = 80
"""The port of an http endpoint that names none, as http has it."""


class RuntimeRefusedError(Exception):
    """A runtime refused, with the code, the problem, the fix and its details."""

    def __init__(self, code: str, problem: str, fix: str, details: dict[str, str]) -> None:
        super().__init__(problem)
        self.code = code
        self.problem = problem
        self.fix = fix
        self.details = details


@dataclass(frozen=True)
class Runtime:
    """The LM Studio one run talks to."""

    endpoint: str
    """The runtime's endpoint, as troupe gave it: what errors name."""
    api_host: str
    """The endpoint's host and port, as the library takes them: ``127.0.0.1:1234``, or
    ``[::1]:1234`` for an IPv6 address."""
    model: str
    price: Price | None = None
    """The model's price troupe gave in run/start, the only one the runner may estimate a cost
    from; None when the theatre doesn't price the model."""


def _unsupported(endpoint: str, problem: str, fix: str) -> RuntimeRefusedError:
    return RuntimeRefusedError(
        "lm-studio.unsupported-endpoint", problem, fix, {"endpoint": shown(endpoint)}
    )


def shown(endpoint: str) -> str:
    """``endpoint`` as an error may show it: without any user info, which can hold a password."""
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return "(an endpoint that can't be read)"
    if parts.username is None and parts.password is None:
        return endpoint
    host = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def _parts(endpoint: str) -> SplitResult:
    try:
        parts = urlsplit(endpoint)
        parts.port  # noqa: B018 - parsing the port is what refuses one that isn't a number
    except ValueError as error:
        raise _unsupported(
            endpoint,
            f"The runtime's endpoint {shown(endpoint)!r} isn't a URL the runner can read: {error}.",
            "Give the runtime LM Studio's server root, such as http://127.0.0.1:1234.",
        ) from None
    return parts


def api_host(endpoint: str) -> str:
    """The library's host and port for ``endpoint``. Refused when the endpoint is https, or has a
    path, user info, a query or a fragment: the library connects only over plain ws://, to the
    server's root."""
    parts = _parts(endpoint)
    if parts.scheme == "https":
        raise _unsupported(
            endpoint,
            f"The runtime's endpoint {endpoint} is https, but LM Studio's own client library "
            "connects only over plain ws://, so the runner can't reach it there.",
            "Give the runtime LM Studio's plain http address, such as http://127.0.0.1:1234.",
        )
    if parts.scheme != "http" or not parts.hostname:
        raise _unsupported(
            endpoint,
            f"The runtime's endpoint {shown(endpoint)!r} isn't an http address with a host.",
            "Give the runtime LM Studio's server root, such as http://127.0.0.1:1234.",
        )
    if parts.username is not None or parts.query or parts.fragment:
        raise _unsupported(
            endpoint,
            f"The runtime's endpoint {shown(endpoint)} holds user info, a query or a fragment, "
            "which LM Studio's own API doesn't take.",
            "Give the runtime LM Studio's server root, such as http://127.0.0.1:1234.",
        )
    port = parts.port if parts.port is not None else DEFAULT_HTTP_PORT
    host = parts.hostname
    bracketed = f"[{host}]" if ":" in host else host
    if parts.path not in ("", "/"):
        root = f"http://{bracketed}" + ("" if parts.port is None else f":{port}")
        raise _unsupported(
            endpoint,
            f"The runtime's endpoint {endpoint} has the path {parts.path}, but LM Studio's own API "
            "lives at the server's root. A runtime at /v1 is LM Studio's OpenAI-compatible API, "
            "which the OpenAI runner uses.",
            f"Give the runtime the endpoint {root}.",
        )
    return f"{bracketed}:{port}"


def from_run_start(params: RunStartParams, environ: Mapping[str, str]) -> Runtime:
    """The run's runtime, from run/start. Refused when there's no runtime or no model, when the
    endpoint can't be used, when the runtime has a credential, and when the environment holds one
    run/start doesn't mention."""
    runtime = params.runtime
    if runtime is None:
        raise RuntimeRefusedError(
            "lm-studio.no-runtime",
            "run/start names no runtime, so the LM Studio runner has no LM Studio to talk to.",
            "Name a runtime for the actor, such as troupe config set "
            "actors.<name>.runtime=lm-studio.",
            {"where": "runtime"},
        )
    if not runtime.model:
        raise RuntimeRefusedError(
            "lm-studio.no-runtime",
            "The runtime names no model.",
            "Give the actor, or its runtime, the model LM Studio should run.",
            {"where": "runtime.model"},
        )
    if runtime.credential:
        raise RuntimeRefusedError(
            "lm-studio.credential-unsupported",
            f"The runtime {runtime.name} has a credential, but LM Studio's own client library "
            "(lmstudio) has no way to send an LM Studio API token, so the runner can't use it.",
            "Turn off Require Authentication in LM Studio's server settings, or remove the "
            f"runtime's credential (troupe config unset runtimes.{runtime.name}.credential).",
            {"where": "runtime.credential"},
        )
    if environ.get(CREDENTIAL_VARIABLE):
        raise RuntimeRefusedError(
            "lm-studio.credential-mismatch",
            f"{CREDENTIAL_VARIABLE} is set, but run/start says the run has no credential.",
            "troupe sets the variable only when the runtime has a credential; start the runner "
            "through troupe, or report the mismatch.",
            {"where": CREDENTIAL_VARIABLE},
        )
    return Runtime(
        endpoint=runtime.endpoint,
        api_host=api_host(runtime.endpoint),
        model=runtime.model,
        price=runtime.price,
    )


__all__ = [
    "DEFAULT_HTTP_PORT",
    "Runtime",
    "RuntimeRefusedError",
    "api_host",
    "from_run_start",
    "shown",
]
