"""The run's runtime: the service the runner talks to (spec: openai-chat-runner, "The service comes
from the run's runtime"; openai-style-runner design D2, D11).

The runtime's endpoint, model and credential come from troupe (#278), never from the runner's
options. run/start carries the runtime as troupe resolved it, and the credential's value is in
the runner's environment as TROUPE_RUNTIME_CREDENTIAL (spec: runner-protocol). This module is the
one place the runner touches the runtime.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from troupe_plugin_sdk.credential import CREDENTIAL_VARIABLE, CredentialError, runtime_credential
from troupe_plugin_sdk.runner import RunStartParams
from troupe_runner_openai_chat.service import Endpoint, EndpointError, parse_endpoint


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

    @classmethod
    def checked(cls, endpoint: str, model: str, credential: str | None) -> "Runtime":
        """A Runtime from its parts, refused when the endpoint isn't a base http or https URL, the
        model is empty, or a credential would go in the clear to another machine."""
        try:
            parsed = parse_endpoint(endpoint)
        except EndpointError as error:
            raise RuntimeRefusedError(
                "openai-chat.no-runtime",
                f"The runtime's endpoint can't be used: {error}",
                "Give the runtime an endpoint such as https://api.openai.com/v1.",
                {"where": "runtime.endpoint"},
            ) from None
        if not model:
            raise RuntimeRefusedError(
                "openai-chat.no-runtime",
                "The runtime names no model.",
                "Give the runtime the model its service should run.",
                {"where": "runtime.model"},
            )
        credential = credential or None
        if parsed.is_insecure_for(credential is not None):
            raise RuntimeRefusedError(
                "openai-chat.insecure-endpoint",
                f"The runtime's endpoint {endpoint} is plain http to another machine, so its "
                "credential would travel in the clear.",
                "Use the service's https endpoint. Plain http is only for a server on this "
                "machine (localhost or a loopback address).",
                {"endpoint": endpoint},
            )
        return cls(parsed, model, credential)


def from_run_start(params: RunStartParams, environ: Mapping[str, str]) -> Runtime:
    """The run's runtime: run/start's, with its credential from ``environ``. Refused when there's
    no runtime, when run/start and ``environ`` disagree about the credential, and as
    Runtime.checked refuses."""
    if params.runtime is None:
        raise RuntimeRefusedError(
            "openai-chat.no-runtime",
            "run/start names no runtime, so the OpenAI-style runner has no service to talk to.",
            "Name a runtime for the actor, such as troupe config set actors.<name>.runtime=openai.",
            {"where": "runtime"},
        )
    try:
        credential = runtime_credential(params, environ)
    except CredentialError as error:
        raise RuntimeRefusedError(
            "openai-chat.credential-mismatch",
            f"{error}, so the runner can't tell whether to send a credential.",
            "troupe sets the variable exactly when run/start says the runtime has a credential; "
            "start the runner through troupe, or report the mismatch.",
            {"where": CREDENTIAL_VARIABLE},
        ) from None
    return Runtime.checked(params.runtime.endpoint, params.runtime.model, credential)


__all__ = ["Runtime", "RuntimeRefusedError", "from_run_start"]
