"""The performance aggregate (spec: performances; performances design D1 to D3).

A performance is one run of your process: every ``troupe perform`` records one, and each of its
steps is a run (troupe.core.runs.aggregate). It is its own stream, keyed by a UUID perform mints
beside the run id. Its events:

- ``Performance.Started``: recorded in the same batch as its first run's start, so neither is
  ever recorded without the other. It holds what was performed (``{kind: actor, name}``; flows add
  their own kind), its steps in order (each step's actor, and its approvers with where they came
  from when the actor works in a worktree), the direction's artifact reference and the config
  version.
- ``Performance.Ended``: once nothing more will happen in it, with its outcome: ``completed``,
  ``failed``, ``rejected`` or ``cancelled``. It is recorded in the same batch as the event that
  settles the performance: the run's end, troupe's acceptance, a person's answer at the gate, or a
  person's accept or discard of a run whose perform stopped before the performance ended. A
  performance whose work waits at a gate, or whose perform stopped without an end, has none until
  then.

Every event of a performance, and of its runs, names it in its lineage (spec: lineage). A second
end is a fault (a bug or a replay), never retried. The topics are these classes' import paths, so
this module isn't moved without registering the old topics with the library.
"""

from typing import Any, Literal
from uuid import UUID

from eventsourcing.domain import Aggregate, event

from troupe.core.errors import TroupeError

Outcome = Literal["completed", "failed", "rejected", "cancelled"]
OUTCOMES: tuple[Outcome, ...] = ("completed", "failed", "rejected", "cancelled")


def outcome_of(run_outcome: str | None, changes: dict[str, Any] | None = None) -> Outcome:
    """A performance's outcome from its run's, for a run that ended with no gate to follow:
    ``succeeded`` is ``completed``, ``cancelled`` is ``cancelled``, and every other is ``failed``
    (performances design D3). A run that succeeded but whose changes couldn't be captured is
    ``failed`` too: its work can never reach its gate, and only a discard settles it (owner,
    2026-11-28, troupe#545)."""
    if run_outcome == "succeeded":
        uncaptured = changes is not None and "error" in changes
        return "failed" if uncaptured else "completed"
    if run_outcome == "cancelled":
        return "cancelled"
    return "failed"


def _out_of_sequence(performance_id: str, problem: str) -> TroupeError:
    return TroupeError(
        "performance.out-of-sequence",
        problem=f"Performance {performance_id}: {problem}",
        fix="This is a fault in troupe, or a replay of events already recorded: nothing was "
        "written for it. Report it, with the performance id, at "
        "https://github.com/troupe-run/troupe/issues",
        details={"performance": performance_id},
    )


class Performance(Aggregate):
    """One performance, from its start to its end."""

    @staticmethod
    def create_id(performance_id: str) -> UUID:
        return UUID(performance_id)

    @event("Started")
    def __init__(
        self,
        performance_id: str,
        performed: dict[str, Any],
        steps: list[dict[str, Any]],
        direction: str,
        config: list[str],
    ) -> None:
        self.performance_id = performance_id
        self.performed = performed
        self.steps = steps
        self.direction = direction
        self.config = config
        self.outcome: Outcome | None = None

    def end(self, outcome: Outcome) -> None:
        """Record the performance's end with ``outcome``. Refused if it has ended already."""
        if self.outcome is not None:
            raise _out_of_sequence(
                self.performance_id, f"its end is already recorded ({self.outcome})."
            )
        self._ended(outcome=outcome)

    @event("Ended")
    def _ended(self, outcome: Outcome) -> None:
        self.outcome = outcome


STARTED = "troupe.core.runs.performance:Performance.Started"
ENDED = "troupe.core.runs.performance:Performance.Ended"
TOPICS = (STARTED, ENDED)
"""Every topic a performance records."""
