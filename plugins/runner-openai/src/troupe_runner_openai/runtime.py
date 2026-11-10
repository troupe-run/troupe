"""The run's runtime: the service the runner talks to (spec: openai-runner, "The service comes
from the run's runtime"; openai-style-runner design D2, D11).

The runtime's endpoint, model and credential come from troupe (#278), never from the runner's
options. run/start carries the runtime as troupe resolved it, and the credential's value is in
the runner's environment as TROUPE_RUNTIME_CREDENTIAL (spec: runner-protocol). This module is the
one place the runner touches the runtime.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from troupe_plugin_sdk.credential import (
    CREDENTIAL_VARIABLE,
    CredentialError,
    runtime_credential,
    well_formed,
)
from troupe_plugin_sdk.runner import Price, RunStartParams
from troupe_runner_openai.service import Endpoint, EndpointError, parse_endpoint


class RuntimeRefusedError(Exception):
    """A runtime refused, with the code, where it is, the problem and the fix, and its details."""

    def __init__(self, code: str, problem: str, fix: str, details: dict[str, str]) -> None:
        super().__init__(problem)
        self.code = code
        self.problem = problem
        self.fix = fix
        self.details = details


@dataclass(frozen=True)
class Runtime:
    """The service one run talks to. The credential never shows in its repr."""

    endpoint: Endpoint
    model: str
    credential: str | None = field(default=None, repr=False)
    price: Price | None = None
    """The model's price troupe gave in run/start, the only one the runner may estimate a cost
    from (spec: openai-runner, "Cost is estimated from troupe's price when the service reports
    none"); None when the theatre doesn't price the model."""

    @classmethod
    def checked(
        cls, endpoint: str, model: str, credential: str | None, price: Price | None = None
    ) -> "Runtime":
        """A Runtime from its parts, refused when the endpoint isn't a base http or https URL with a
        path, the model is empty, or a credential would go in the clear to another machine."""
        try:
            parsed = parse_endpoint(endpoint)
        except EndpointError as error:
            raise RuntimeRefusedError(
                "openai.no-runtime",
                f"The runtime's endpoint can't be used: {error}",
                "Give the runtime an endpoint such as https://api.openai.com/v1.",
                {"where": "runtime.endpoint"},
            ) from None
        if not parsed.has_path:
            # An OpenAI-style service serves its API under a path, such as /v1; at a server's root
            # is often another API, such as Ollama's own (runtime-checks design D5).
            raise RuntimeRefusedError(
                "openai.no-runtime",
                f"The runtime's endpoint, {endpoint}, has no path, but an OpenAI-style service "
                "serves its API under one, such as /v1: the runner's requests go to "
                "<endpoint>/responses.",
                "Give the runtime the endpoint with its API's path, such as "
                "http://127.0.0.1:11434/v1 for Ollama's OpenAI-style API, or "
                "https://api.openai.com/v1.",
                {"where": "runtime.endpoint"},
            )
        if not model:
            raise RuntimeRefusedError(
                "openai.no-runtime",
                "The runtime names no model.",
                "Give the runtime the model its service should run.",
                {"where": "runtime.model"},
            )
        credential = credential or None
        if credential is not None and not well_formed(credential):
            raise RuntimeRefusedError(
                "openai.malformed-credential",
                f"The run's credential in {CREDENTIAL_VARIABLE} holds a character a request header "
                "can't carry, such as a space, a line ending left from the file it was read from, "
                "or a letter outside ASCII.",
                "Set the runtime's key variable to the key alone: only visible ASCII characters, "
                "with no spaces or line endings.",
                {"where": CREDENTIAL_VARIABLE},
            )
        if parsed.is_insecure_for(credential is not None):
            raise RuntimeRefusedError(
                "openai.insecure-endpoint",
                f"The runtime's endpoint {endpoint} is plain http to another machine, so its "
                "credential would travel in the clear.",
                "Use the service's https endpoint. Plain http is only for a server on this "
                "machine (localhost or a loopback address).",
                {"endpoint": endpoint},
            )
        return cls(parsed, model, credential, price)


def from_run_start(params: RunStartParams, environ: Mapping[str, str]) -> Runtime:
    """The run's runtime: run/start's, with its credential from ``environ``. Refused when there's
    no runtime, when run/start and ``environ`` disagree about the credential, and as
    Runtime.checked refuses."""
    if params.runtime is None:
        raise RuntimeRefusedError(
            "openai.no-runtime",
            "run/start names no runtime, so the OpenAI runner has no service to talk to.",
            "Name a runtime for the actor, such as troupe config set actors.<name>.runtime=openai.",
            {"where": "runtime"},
        )
    try:
        credential = runtime_credential(params, environ)
    except CredentialError as error:
        raise RuntimeRefusedError(
            "openai.credential-mismatch",
            f"{error}, so the runner can't tell whether to send a credential.",
            "troupe sets the variable exactly when run/start says the runtime has a credential; "
            "start the runner through troupe, or report the mismatch.",
            {"where": CREDENTIAL_VARIABLE},
        ) from None
    return Runtime.checked(
        params.runtime.endpoint, params.runtime.model, credential, params.runtime.price
    )


__all__ = ["Runtime", "RuntimeRefusedError", "from_run_start"]
