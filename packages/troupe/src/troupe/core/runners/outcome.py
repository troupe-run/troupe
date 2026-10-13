"""Deriving a run's one outcome from its facts (spec: actor-runners; design D4).

Every rule is here, in one pure function, so it can be property-tested. The facts are what the run
host observed; the outcome uses them together. Success takes all three signals: a result with status
ok, a passing effect check, and a runner that exited with code 0. The exit code alone never makes
a run succeed.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from troupe.core.errors import TroupeError
from troupe.core.runners.effects import EffectVerdict
from troupe.core.runners.limits import RunLimits
from troupe.core.runners.protocol import ResultEvent


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed-out"
    CRASHED = "crashed"
    COULD_NOT_START = "could-not-start"


class Ending(StrEnum):
    """How the runner process ended."""

    EXITED = "exited"
    KILLED = "killed"
    """Killed by troupe after the grace period, so its exit code says nothing."""
    NEVER_STARTED = "never-started"


class StopReason(StrEnum):
    """Why troupe asked the runner to stop, when it did."""

    CALLER = "caller"
    RUN_TIMEOUT = "run-timeout"
    AUTHENTICATION = "authentication"
    TRANSCRIPT_LIMIT = "transcript-limit"
    PROTOCOL = "protocol"


@dataclass(frozen=True)
class RunFacts:
    """What the run host observed about one run attempt."""

    limits: RunLimits
    ending: Ending
    exit_code: int | None = None
    start_error: TroupeError | None = None
    violation: TroupeError | None = None
    stop: StopReason | None = None
    result: ResultEvent | None = None
    effect: EffectVerdict | None = None
    """Checked only when the result's status is ok."""


def derive_outcome(facts: RunFacts) -> tuple[Outcome, TroupeError | None]:
    """The run's outcome and, for every outcome but succeeded and cancelled, its error.

    The first matching row of design D4's table wins.
    """
    if facts.start_error is not None:
        return Outcome.COULD_NOT_START, facts.start_error
    if facts.violation is not None:
        return Outcome.CRASHED, facts.violation
    if facts.stop is StopReason.AUTHENTICATION:
        return Outcome.FAILED, TroupeError(
            "run.authentication",
            problem="The runner's engine couldn't authenticate, so the run was stopped rather than "
            "left retrying.",
            fix="Check the credential the runner was given, then run it again.",
        )
    if facts.stop is StopReason.TRANSCRIPT_LIMIT:
        limit = facts.limits.transcript_max_bytes
        return Outcome.FAILED, TroupeError(
            "run.transcript-too-large",
            problem=f"The run's transcript passed its limit of {limit} bytes, so the run was "
            "stopped. The transcript up to that point was kept.",
            fix="Raise RUN_TRANSCRIPT_MAX_BYTES for this run if that much output is expected.",
            details={"limitBytes": limit},
        )
    result = facts.result
    if result is not None and result.status == "error":
        return Outcome.FAILED, TroupeError(
            "run.error-result",
            problem=f"The runner reported an error: {result.message or '(no message)'}",
            fix="Check the run's transcript for what went wrong.",
            details={"message": result.message},
        )
    if result is not None:
        if facts.effect is None:
            raise ValueError("a run with an ok result needs its effect verdict")
        if not facts.effect.passed:
            return Outcome.FAILED, facts.effect.error
        if facts.ending is not Ending.EXITED or facts.exit_code != 0:
            ended = (
                "had to be killed after it didn't exit"
                if facts.ending is not Ending.EXITED
                else f"exited with code {facts.exit_code}"
            )
            return Outcome.FAILED, TroupeError(
                "run.unclean-exit",
                problem=f"The runner reported success but {ended}, so the run's state is "
                "uncertain.",
                fix="Check the run's effects and transcript before relying on them.",
                details={"exitCode": facts.exit_code, "ending": str(facts.ending)},
            )
        return Outcome.SUCCEEDED, None
    if facts.stop is StopReason.RUN_TIMEOUT:
        timeout = facts.limits.run_timeout
        return Outcome.TIMED_OUT, TroupeError(
            "run.timeout",
            problem=f"The run was still going after its limit of {timeout:g}s, so it was stopped.",
            fix="Raise RUN_TIMEOUT_SECONDS for this run if it needs longer.",
            details={"limitSeconds": timeout},
        )
    if facts.stop is StopReason.CALLER:
        return Outcome.CANCELLED, None
    return Outcome.CRASHED, TroupeError(
        "runner.crashed",
        problem="The runner stopped without reporting a result"
        + (f" (exit code {facts.exit_code})." if facts.exit_code is not None else "."),
        fix="Check the run's standard error and transcript for why it stopped.",
        details={"exitCode": facts.exit_code, "ending": str(facts.ending)},
    )


@dataclass(frozen=True)
class RunOutcome:
    """Everything about how one run attempt ended, for recording (design D4)."""

    run_id: str
    outcome: Outcome
    error: TroupeError | None
    result: ResultEvent | None
    exit_code: int | None
    ending: Ending
    transcript: str | None
    """The transcript's artifact reference; None only when the runner never started."""
    stderr: str | None
    limits: RunLimits

    def to_data(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "outcome": str(self.outcome),
            "error": None if self.error is None else self.error.to_data(),
            "result": None if self.result is None else self.result.to_data(),
            "exitCode": self.exit_code,
            "ending": str(self.ending),
            "transcript": self.transcript,
            "stderr": self.stderr,
            "limits": self.limits.to_data(),
        }
