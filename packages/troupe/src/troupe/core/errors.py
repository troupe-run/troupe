"""Structured errors, mirroring protocol/schemas/error.schema.json.

Every failure troupe reports is a TroupeError. Surfaces render it in their own words; the code
identifies it. Each code is declared once, in CODES, with the exit code the CLI uses for it.
"""

from dataclasses import dataclass, field
from typing import Any

from troupe.core.exit_codes import ExitCode

BUG_REPORT_URL = "https://github.com/troupe-run/troupe/issues"

CODES: dict[str, ExitCode] = {
    "internal.unexpected": ExitCode.FAILURE,
    "usage.invalid": ExitCode.USAGE,
    "usage.unknown-command": ExitCode.USAGE,
    "usage.unknown-flag": ExitCode.USAGE,
    "usage.dash-value": ExitCode.USAGE,
    "lock.timeout": ExitCode.FAILURE,
    "lock.already-held": ExitCode.FAILURE,
    "replace.in-use": ExitCode.FAILURE,
    "replace.failed": ExitCode.FAILURE,
    "runner.start-failed": ExitCode.FAILURE,
    "runner.incompatible": ExitCode.FAILURE,
    "runner.start-timeout": ExitCode.FAILURE,
    "runner.protocol": ExitCode.FAILURE,
    "runner.crashed": ExitCode.FAILURE,
    "run.error-result": ExitCode.FAILURE,
    "run.effect-missing": ExitCode.FAILURE,
    "run.timeout": ExitCode.FAILURE,
    "run.authentication": ExitCode.FAILURE,
    "run.transcript-too-large": ExitCode.FAILURE,
    "run.unclean-exit": ExitCode.FAILURE,
    "artifact.missing": ExitCode.FAILURE,
    "artifact.corrupt": ExitCode.FAILURE,
    "artifact.write-failed": ExitCode.FAILURE,
    "artifact.unknown-store": ExitCode.FAILURE,
    # The event store, identity and version control (event-store design D12).
    "events.version-conflict": ExitCode.FAILURE,
    "events.stream-forked": ExitCode.FAILURE,
    "events.settle-incomplete": ExitCode.FAILURE,
    "events.missing-parent": ExitCode.FAILURE,
    "events.malformed-record": ExitCode.FAILURE,
    "events.unknown-format": ExitCode.FAILURE,
    "events.lineage-invalid": ExitCode.FAILURE,
    "events.cause-unknown": ExitCode.FAILURE,
    "events.unknown-store": ExitCode.FAILURE,
    "identity.unresolved": ExitCode.FAILURE,
    "identity.invalid-override": ExitCode.FAILURE,
    "identity.ambiguous": ExitCode.FAILURE,
    "identity.unknown-source": ExitCode.FAILURE,
    "vcs.unknown-adapter": ExitCode.FAILURE,
    "vcs.failed": ExitCode.FAILURE,
    "command.timeout": ExitCode.FAILURE,
    "command.not-found": ExitCode.FAILURE,
    "command.output-too-large": ExitCode.FAILURE,
    "environment.policy-invalid": ExitCode.FAILURE,
    # perform, status and logs (perform-status-logs design D15). docs/runs.md lists them.
    "policy.invalid-value": ExitCode.FAILURE,
}


@dataclass(eq=False)
class TroupeError(Exception):
    """A failure with a stable code, the problem, the fix, and optionally the path concerned."""

    code: str
    problem: str
    fix: str
    path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.code not in CODES:
            msg = f"undeclared error code {self.code!r}: add it to troupe.core.errors.CODES"
            raise ValueError(msg)
        super().__init__(self.problem)

    @property
    def exit_code(self) -> ExitCode:
        return CODES[self.code]

    def to_data(self) -> dict[str, Any]:
        """The error as protocol data (error.schema.json)."""
        data: dict[str, Any] = {"code": self.code, "problem": self.problem, "fix": self.fix}
        if self.path is not None:
            data["path"] = self.path
        if self.details:
            data["details"] = self.details
        return data
