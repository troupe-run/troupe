"""The run's runtime: the Ollama service the runner talks to (spec: ollama-runner, "The service
comes from the run's runtime"; ollama-uses-runtime design D2, D3, D4).

The endpoint and the model come from troupe (spec: runtimes), never from the runner's options, and
the runner writes neither down: troupe's built-in ``ollama`` runtime holds Ollama's default address.
run/start carries the runtime as troupe resolved it, and this module is the one place the runner
reads it.

The runner contract's own pattern already holds the endpoint to an http or https URL with no user
info, query or fragment, so a run/start with one of those never reaches here. What's checked here is
what Ollama's native API adds: the API is at the root, so no path, and a port and host name a
connection can use.
"""

import re
from dataclasses import dataclass

from troupe_plugin_sdk.runner import RunStartParams, RunStartRuntime

ENV_PREFIX = "TROUPE_RUNTIME_"
"""The prefix of the variables that override a runtime's fields in the person's environment
(spec: runtimes). troupe's core has the same rule, which the runner can't import."""

_ENDPOINT = re.compile(
    r"\Ahttps?://"
    r"(?:\[[0-9A-Fa-f:.]+\]|(?:[A-Za-z0-9-]{1,63}\.)*[A-Za-z0-9-]{1,63})"
    r"(?::(?:6553[0-5]|655[0-2][0-9]|65[0-4][0-9]{2}|6[0-4][0-9]{3}|[1-5][0-9]{4}|[0-9]{1,4}))?"
    r"/?\Z"
)
"""An endpoint Ollama's native API can be reached at: a host, an optional port up to 65535, and no
path."""


def env_name(runtime: str, field: str) -> str:
    """The variable that sets ``field`` of ``runtime``: ``TROUPE_RUNTIME_LM_STUDIO_ENDPOINT``."""
    return f"{ENV_PREFIX}{runtime.upper().replace('-', '_')}_{field.upper()}"


class RuntimeRefusedError(Exception):
    """A runtime refused, with the code, where it is, the problem and the fix."""

    def __init__(self, code: str, where: str, problem: str, fix: str) -> None:
        super().__init__(f"{where}: {problem}")
        self.code = code
        self.where = where
        self.problem = problem
        self.fix = fix


@dataclass(frozen=True)
class Runtime:
    """The service one run talks to."""

    name: str
    endpoint: str
    """Where requests go, without a trailing ``/``."""
    model: str

    def endpoint_fix(self) -> str:
        """How a person points this runtime somewhere else."""
        return endpoint_fix(self.name)


def endpoint_fix(name: str) -> str:
    """How a person points the runtime ``name`` somewhere else. The runner can't see where the
    endpoint came from, so it says the variable wins over config."""
    variable = env_name(name, "endpoint")
    return (
        f"set runtimes.{name}.endpoint in config (troupe config set "
        f"runtimes.{name}.endpoint=<url>), or {variable} in your environment, which wins over "
        f"config: if {variable} is set, change or unset it"
    )


def _endpoint(name: str, value: str) -> str:
    if _ENDPOINT.match(value) is not None:
        return value.rstrip("/")
    rest = value.partition("://")[2]
    if "/" in rest.rstrip("/") or rest.endswith("//"):
        problem = (
            f"{value!r} has a path, but Ollama's own API is at the root: the runner adds /api/... "
            "itself. An address ending in /v1 is Ollama's OpenAI-style API, which is for the "
            "openai runner."
        )
    else:
        problem = (
            f"{value!r} isn't a host and an optional port: each part of a host name is 1 to 63 "
            "letters, digits or hyphens, and a port is at most 65535."
        )
    fix = endpoint_fix(name)
    raise RuntimeRefusedError(
        "ollama.invalid-runtime",
        "runtime.endpoint",
        problem,
        f"Give the runtime where Ollama listens, such as http://127.0.0.1:11434: {fix}.",
    )


def from_run_start(params: RunStartParams) -> Runtime:
    """The run's runtime. Refused when run/start names none, when the runtime has a credential,
    which the runner never sends (design D3), and when its endpoint isn't one Ollama's API can be
    reached at (design D4). The credential's variable is never read."""
    runtime = params.runtime
    if runtime is None:
        raise RuntimeRefusedError(
            "ollama.no-runtime",
            "runtime",
            "run/start names no runtime, so the Ollama runner has no service to talk to.",
            "Name a runtime for the actor, such as troupe config set actors.<name>.runtime=ollama, "
            "and give it a model with actors.<name>.model.",
        )
    return checked(runtime)


def checked(runtime: RunStartRuntime) -> Runtime:
    """``runtime`` as the runner uses it, refused when it has a credential or an endpoint the
    runner can't use."""
    if runtime.credential:
        raise RuntimeRefusedError(
            "ollama.credential-unsupported",
            "runtime.credential",
            f"The runtime {runtime.name!r} has a credential, but the Ollama runner sends none, so "
            "a service that needs it would refuse every request.",
            "Name a runtime without a credential for the actor, such as the built-in ollama "
            "(troupe config set actors.<name>.runtime=ollama), or use a runner that sends a key, "
            "such as openai, for a service that needs one.",
        )
    if runtime.endpoint is None:
        # An in-process runtime, which config wouldn't let an Ollama actor name
        # (in-process-runner design D5).
        raise RuntimeRefusedError(
            "ollama.invalid-runtime",
            "runtime.endpoint",
            f"The runtime {runtime.name!r} has no endpoint: it's in-process, for a runner that "
            "loads its model itself, and the Ollama runner talks to Ollama at an endpoint.",
            "Name a runtime with Ollama's endpoint for the actor, such as the built-in ollama "
            "(troupe config set actors.<name>.runtime=ollama).",
        )
    return Runtime(runtime.name, _endpoint(runtime.name, runtime.endpoint), runtime.model)


__all__ = [
    "ENV_PREFIX",
    "Runtime",
    "RuntimeRefusedError",
    "checked",
    "endpoint_fix",
    "env_name",
    "from_run_start",
]
