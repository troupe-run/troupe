"""The run aggregate (spec: runs; perform-status-logs design D8).

A run is its own stream, keyed by its run id (a UUID minted by perform). Its events:

- ``Run.Started``: recorded when the runner's init arrives, or at the end of a run that never sent
  one. It holds the actor's name, the runner requested and the one init reported, the stage's
  admission, the effect check, and the instructions and options as artifact references.
- ``Run.Reported``: one per run event, holding the runner's ``seq`` and the event as received. The
  ``seq`` is payload, never the stream's version (the library numbers versions from 1).
- ``Run.Ended``: the outcome the run host derived, and whether recording failed part-way.

A field with nothing to say (no init, so no reported runner; recording that didn't fail) is left
out of the stored event, so each such parameter defaults to None and the event reads back without
it (omit-nulls design D4).

The aggregate refuses a ``seq`` that isn't the next one, a report before the start or after the end,
and a second end: each is a fault (a bug or a replay), never retried. The topics are these classes'
import paths, so this module isn't moved without registering the old topics with the library.
"""

from typing import Any
from uuid import UUID

from eventsourcing.domain import Aggregate, event

from troupe.core.errors import TroupeError


def _out_of_sequence(run_id: str, problem: str, **details: object) -> TroupeError:
    return TroupeError(
        "run.out-of-sequence",
        problem=f"Run {run_id}: {problem}",
        fix="This is a fault in troupe, or a replay of events already recorded: nothing was "
        "written for it. Report it, with the run id, at https://github.com/troupe-run/troupe/issues",
        details={"run": run_id, **details},
    )


class Run(Aggregate):
    """One run of an actor, from its start to its end."""

    @staticmethod
    def create_id(run_id: str) -> UUID:
        return UUID(run_id)

    @event("Started")
    def __init__(
        self,
        run_id: str,
        actor: str,
        runner_requested: str,
        stage: dict[str, Any],
        effect_check: dict[str, Any],
        instructions: str,
        options: str,
        runner_reported: dict[str, Any] | None = None,
    ) -> None:
        self.run_id = run_id
        self.actor = actor
        self.runner_requested = runner_requested
        self.runner_reported = runner_reported
        self.stage = stage
        self.effect_check = effect_check
        self.instructions = instructions
        self.options = options
        self.next_seq = 0
        self.ended = False

    def report(self, seq: int, run_event: dict[str, Any]) -> None:
        """Record the run event numbered ``seq``. Refused unless it is the next one."""
        if self.ended:
            raise _out_of_sequence(
                self.run_id, f"run event {seq} arrived after the run ended.", seq=seq
            )
        if seq != self.next_seq or run_event.get("seq") != seq:
            raise _out_of_sequence(
                self.run_id,
                f"run event {seq} isn't the next one; the run expects {self.next_seq}.",
                seq=seq,
                expected=self.next_seq,
            )
        self._reported(seq=seq, event=run_event)

    @event("Reported")
    def _reported(self, seq: int, event: dict[str, Any]) -> None:
        self.next_seq = seq + 1

    def end(self, outcome: dict[str, Any], recording: dict[str, Any] | None) -> None:
        """Record how the run ended. Refused if it already has."""
        if self.ended:
            raise _out_of_sequence(self.run_id, "the run's end is already recorded.")
        self._ended(outcome=outcome, recording=recording)

    @event("Ended")
    def _ended(self, outcome: dict[str, Any], recording: dict[str, Any] | None = None) -> None:
        self.ended = True


STARTED = "troupe.core.runs.aggregate:Run.Started"
REPORTED = "troupe.core.runs.aggregate:Run.Reported"
ENDED = "troupe.core.runs.aggregate:Run.Ended"
TOPICS = (STARTED, REPORTED, ENDED)
"""Every topic a run records."""
