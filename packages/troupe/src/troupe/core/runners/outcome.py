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
from troupe.core.runners.effects import AuditFindings, EffectVerdict
from troupe.core.runners.limits import RunLimits
from troupe_plugin_sdk.runner import FailureReason, ResultEvent

FAILURES: dict[FailureReason, tuple[str, str]] = {
    "authentication": (
        "The engine refused the credential",
        "Check the credential the actor's runtime names, and that it's allowed to use the model, "
        "then run it again.",
    ),
    "quota": (
        "The account is out of quota",
        "Add credit or quota to the account the actor's runtime uses, or give the actor another "
        "runtime.",
    ),
    "rate-limit": (
        "The engine kept rate limiting the run, past what the runner waits for",
        "Wait for the limit to reset, or run fewer actors on this account at once, then run it "
        "again.",
    ),
    "network": (
        "The engine couldn't be reached",
        "Check the network and the endpoint of the actor's runtime, then run it again.",
    ),
    "server": (
        "The engine kept failing on its side",
        "Run it again later; if it keeps failing, check the service's status.",
    ),
    "configuration": (
        "The endpoint or model can't serve the run",
        "Check the endpoint and model of the actor's runtime: the runner's message says what it "
        "found there.",
    ),
    "context-length": (
        "The conversation outgrew the model's context",
        "Give the actor a smaller task, or a model with a longer context.",
    ),
    "output-limit": (
        "An answer was cut at the model's output limit",
        "Raise the output limit in the actor's runner options if it has one, or give the actor a "
        "smaller task.",
    ),
    "refused": (
        "The model refused, or the service's content filter stopped it",
        "Read the refusal in the runner's message, and change the direction or the character.",
    ),
    "turn-limit": (
        "The run reached its turn limit",
        "Raise the turn limit in the actor's runner options to let it go further, or give it a "
        "smaller task.",
    ),
    "budget": (
        "The run spent its budget",
        "Raise the budget in the actor's runner options to let it go further, or give it a "
        "smaller task.",
    ),
    "cancelled": (
        "The run was cancelled",
        "Nothing to fix: the run was asked to stop. Run it again if it should finish.",
    ),
    "engine": (
        "The engine failed in a way of its own",
        "Check the run's transcript for what the engine sent; if it's the engine's fault, report "
        "it to its makers.",
    ),
    "runner": (
        "The runner failed",
        "Check the run's standard error for what went wrong, and report it to the runner's makers.",
    ),
    "other": (
        "The runner reported an error",
        "Check the run's transcript for what went wrong.",
    ),
}
"""For each reason a result can fail with: what went wrong, and what to do about it. Every reason
in the contract's list has an entry."""


def error_result(result: ResultEvent) -> TroupeError:
    """The error for a run whose result had status error, saying why from its reason."""
    if result.reason is None:
        raise ValueError("an error result always has a reason")
    problem, fix = FAILURES[result.reason]
    return TroupeError(
        "run.error-result",
        problem=f"{problem}: {result.message or '(no message)'}",
        fix=fix,
        details={"reason": result.reason, "message": result.message},
    )


class TranscriptFormat(StrEnum):
    """How a stored transcript's lines are written (spec: runs, actor-runners)."""

    NATIVE = "native"
    """Each line is a record as the runner sent it, after masking."""
    KINDS = "kinds"
    """The runner accepted transcript-kinds: each line is a record with its kind
    (protocol/schemas/transcript-record.schema.json)."""


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
    """Troupe's kill ended it (after a violation, a failed start or a grace period), so its exit
    code says nothing. A runner that exited by itself before the kill landed is EXITED."""
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
    """Checked only when the result's status is ok: the expected files' verdict with the audit's.
    The audit's findings for any other result never reach the outcome (failed-run-audit design
    D1)."""

    def __post_init__(self) -> None:
        if (self.exit_code is None) != (self.ending is Ending.NEVER_STARTED):
            raise ValueError(
                "a runner has an exit code exactly when it started (ending isn't never-started)"
            )


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
        return Outcome.FAILED, error_result(result)
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
                details=_exit_details(facts),
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
        details=_exit_details(facts),
    )


def _exit_details(facts: RunFacts) -> dict[str, object]:
    """How the runner ended, and its exit code when it has one: a runner that never started has
    none, so the field is left out (omit-nulls design D3)."""
    details: dict[str, object] = {"ending": str(facts.ending)}
    if facts.exit_code is not None:
        details["exitCode"] = facts.exit_code
    return details


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
    transcript_format: TranscriptFormat | None
    """How the transcript's lines are written; None exactly when ``transcript`` is."""
    stderr: str | None
    limits: RunLimits
    audit: AuditFindings | None = None
    """What the audit of the run's changes found; None exactly when the runner never started, or
    the caller had no workspace to audit (NoAudit). perform always audits, so a recorded end whose
    runner started always has one (require-always-written-fields design D4)."""

    def __post_init__(self) -> None:
        if (self.transcript is None) != (self.transcript_format is None):
            raise ValueError(
                "a run outcome has a transcript format exactly when it has a transcript"
            )

    def to_data(self) -> dict[str, Any]:
        """The outcome as recorded, leaving out what didn't happen: no error, no result, and for
        a runner that never started, no exit code, transcript or standard error."""
        data: dict[str, Any] = {
            "runId": self.run_id,
            "outcome": str(self.outcome),
            "ending": str(self.ending),
            "limits": self.limits.to_data(),
        }
        if self.error is not None:
            data["error"] = self.error.to_data()
        if self.result is not None:
            data["result"] = self.result.to_data()
        if self.exit_code is not None:
            data["exitCode"] = self.exit_code
        if self.transcript is not None:
            data["transcript"] = self.transcript
        if self.transcript_format is not None:
            data["transcriptFormat"] = str(self.transcript_format)
        if self.stderr is not None:
            data["stderr"] = self.stderr
        if self.audit is not None:
            data["audit"] = self.audit.to_data()
        return data
