"""The run's runtime: the service the runner talks to (spec: openai-chat-runner, "The service comes
from the run's runtime"; openai-style-runner design D2, D11).

The runtime's endpoint, model and credential come from troupe (#278), never from the runner's
options. This module is the one place the runner touches the runtime, so the shape #278 settles on
changes it and its tests only. Reading the runtime from run/start waits for that shape: until
then, the runner's tests make a Runtime directly.
"""

from dataclasses import dataclass, field

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


__all__ = ["Runtime", "RuntimeRefusedError"]
