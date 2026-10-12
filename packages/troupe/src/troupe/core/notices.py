"""Notices, mirroring protocol/schemas/notice.schema.json (runner-contract design D7).

A notice tells a person something while troupe works: a long silence, a retry. It has the same
fields as an error (code, problem, fix, and optionally path and details), so every surface renders
both the same way. Each code is declared once, in CODES.
"""

from dataclasses import dataclass, field
from typing import Any

CODES: dict[str, str] = {
    "run.silent": "A run has sent no event for the silence threshold.",
    "run.retrying": "A runner reported that its engine is retrying.",
    # The event store (event-store design D12). docs/event-store.md lists them.
    "events.other-branch": "Uncommitted events made on another branch were left out of a read.",
    "events.order-rebuilt": "The local notification order was rebuilt, so followers start again.",
    "events.incomplete-batch": "A segment ends in an interrupted batch, which was left out.",
    # Runs (perform-status-logs design D10, D11). docs/runs.md lists them.
    "run.cancelling": "Cancel was asked for, and the run is stopping within its grace period.",
    "run.interrupted": "A run has no recorded end, and the perform that ran it has stopped.",
    "run.unfinished-elsewhere": "A run started in another clone has no recorded end here.",
}
"""Every notice code, with what it means."""


@dataclass(frozen=True)
class Notice:
    code: str
    problem: str
    fix: str
    path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.code not in CODES:
            msg = f"undeclared notice code {self.code!r}: add it to troupe.core.notices.CODES"
            raise ValueError(msg)

    def to_data(self) -> dict[str, Any]:
        """The notice as protocol data (notice.schema.json)."""
        data: dict[str, Any] = {"code": self.code, "problem": self.problem, "fix": self.fix}
        if self.path is not None:
            data["path"] = self.path
        if self.details:
            data["details"] = self.details
        return data
