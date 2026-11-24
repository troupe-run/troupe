"""What test_runner_conformance.py and test_runner_conformance_integration.py share."""

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from troupe.core import runtimes
from troupe.core.config.kinds import runtime_problems
from troupe_plugin_sdk.runner import RunStartRuntime

SCRIPTED = [sys.executable, "-m", "troupe_runner_scripted"]

RUNNER_VARIABLE = "TROUPE_CONFORMANCE_RUNNER"
OPTIONS_VARIABLE = "TROUPE_CONFORMANCE_OPTIONS"
RUNTIME_VARIABLE = "TROUPE_CONFORMANCE_RUNTIME"
RUNNER_ACCEPTED = "a JSON array of strings, the runner's command line, whose first isn't empty"
OPTIONS_ACCEPTED = "a JSON object, the run/start options for a short run that succeeds"
RUNTIME_ACCEPTED = (
    'a JSON object holding the runtime\'s "name" and the fields a runtime has in config '
    '("endpoint", "model", "credential": {"env": <variable>}, "prices")'
)
ACTOR = "conformance"
"""The actor troupe resolves the runtime for: it names none of its own (design D3)."""


class ConformanceSetupError(ValueError):
    """A conformance variable that is set but malformed: names the variable, what it must hold
    and the fix, and never the value, which for the runtime could hold a key (design D3)."""

    def __init__(self, variable: str, problem: str, accepted: str) -> None:
        super().__init__(f"{variable} {problem}. Set it to {accepted}, or unset it.")


@dataclass(frozen=True)
class Target:
    """What the env-driven check runs: the runner, its options, its runtime and its credential."""

    argv: list[str]
    options: dict[str, Any]
    runtime: RunStartRuntime | None = None
    credential: str | None = field(default=None, repr=False)

    @property
    def env(self) -> dict[str, str]:
        """The runner's own environment entries: the credential, as a run gives it (design D2)."""
        return {"TROUPE_RUNTIME_CREDENTIAL": self.credential} if self.credential else {}


def _json(env: Mapping[str, str], variable: str, accepted: str) -> object:
    """The JSON ``variable`` holds, or None when it's unset or empty."""
    raw = env.get(variable, "")
    if raw == "":
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        # The position only: the text could be a key pasted in the wrong place.
        where = f"line {error.lineno} column {error.colno}"
        raise ConformanceSetupError(variable, f"isn't JSON (at {where})", accepted) from None


def _runtime(env: Mapping[str, str]) -> tuple[RunStartRuntime | None, str | None]:
    """The runtime TROUPE_CONFORMANCE_RUNTIME gives, as a run resolves it, and its credential's
    value read from ``env``; (None, None) when it gives none (design D1)."""
    data = _json(env, RUNTIME_VARIABLE, RUNTIME_ACCEPTED)
    if data is None:
        return None, None
    if not isinstance(data, dict):
        raise ConformanceSetupError(RUNTIME_VARIABLE, "isn't a JSON object", RUNTIME_ACCEPTED)
    name = data.get("name")
    if not isinstance(name, str):
        raise ConformanceSetupError(
            RUNTIME_VARIABLE, 'has no "name" that is a string', RUNTIME_ACCEPTED
        )
    entry = {key: value for key, value in data.items() if key != "name"}
    problems = runtime_problems(name, entry)
    if problems:
        found = "; ".join(
            f"{'.'.join(problem.path[2:]) or 'name'}: {problem.rule}" for problem in problems
        )
        raise ConformanceSetupError(
            RUNTIME_VARIABLE, f"breaks a runtime's rules ({found})", RUNTIME_ACCEPTED
        )
    config = {runtimes.RUNTIMES: {name: entry}}
    if runtimes.run_model(runtimes.resolve(name, config, env), None) is None:
        raise ConformanceSetupError(
            RUNTIME_VARIABLE,
            f'sets no "model", and neither does troupe\'s runtime {name!r} or '
            f"{runtimes.env_name(name, 'model')}",
            RUNTIME_ACCEPTED,
        )
    run = runtimes.for_run(name, ACTOR, None, config, env)
    return RunStartRuntime.from_data(run.run_start()), run.value


def conformance_target(env: Mapping[str, str]) -> Target:
    """What ``env``'s TROUPE_CONFORMANCE_* variables name. Raises ConformanceSetup for a malformed
    variable, and the runtime's own refusals (a TroupeError) for its credential (design D3)."""
    argv = _json(env, RUNNER_VARIABLE, RUNNER_ACCEPTED)
    if argv is None:
        raise ConformanceSetupError(RUNNER_VARIABLE, "isn't set", RUNNER_ACCEPTED)
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(part, str) for part in argv)
        or argv[0] == ""
    ):
        raise ConformanceSetupError(RUNNER_VARIABLE, "isn't a command line", RUNNER_ACCEPTED)
    options = _json(env, OPTIONS_VARIABLE, OPTIONS_ACCEPTED)
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ConformanceSetupError(OPTIONS_VARIABLE, "isn't a JSON object", OPTIONS_ACCEPTED)
    runtime, credential = _runtime(env)
    return Target(argv, options, runtime, credential)


KEY = "sk-conformance-env-0123456789"
