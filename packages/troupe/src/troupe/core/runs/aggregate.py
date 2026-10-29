"""The run aggregate (spec: runs; perform-status-logs design D8; account-for-every-worktree
design D1 to D4).

A run is its own stream, keyed by its run id (a UUID minted by perform). Its events:

- ``Run.Started``: recorded before the run's workspace is made and its runner starts, once every
  check that can refuse the run has passed. It holds the actor's name, the runner requested, the
  stage's admission, the effect check, the direction as an artifact reference, the config version
  the run used (config-model design D14), and its workspace (worktree-stage design D7). For a
  worktree, that's where the worktree will be, so an event names it before any part of it exists.
  A start recorded by an older troupe also holds the runner its init reported, and the worktree's
  clone mechanisms; both read back.
- ``Run.WorktreeMade``: a worktree run's clone mechanisms, once its worktree is made and before its
  runner starts.
- ``Run.Reported``: one per run event, holding the runner's ``seq`` and the event as received. The
  ``seq`` is payload, never the stream's version (the library numbers versions from 1). The first
  is the runner's init, which names the runner that reported.
- ``Run.Ended``: the outcome the run host derived, whether recording failed part-way, and, for a
  worktree run, the changes captured from its worktree.
- ``Run.ChangesAccepted`` or ``Run.ChangesDiscarded``: what the person did with a worktree run's
  changes. At most one of them, after the end: settling is final (worktree-stage design D6, D7).

A field with nothing to say (recording that didn't fail, a start with no reported runner) is left
out of the stored event, so each such parameter defaults to None and the event reads back without
it (omit-nulls design D4).

The aggregate refuses a ``seq`` that isn't the next one, a report before the start or after the end,
a second end, a worktree made for a run in the theatre, twice, or after the runner reported, and a
second settling of the changes: each is a fault (a bug or a replay), never retried. The commands
that settle changes check the run first (troupe.core.runs.changes), so the aggregate's refusals are
the backstop. The topics are these classes' import paths, so this module isn't moved without
registering the old topics with the library.
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
        direction: str,
        config: list[str],
        runner_reported: dict[str, Any] | None = None,
        workspace: dict[str, Any] | None = None,
    ) -> None:
        self.run_id = run_id
        self.actor = actor
        self.runner_requested = runner_requested
        self.runner_reported = runner_reported
        self.stage = stage
        self.effect_check = effect_check
        self.direction = direction
        self.config = config
        self.workspace = workspace
        self.worktree_made = False
        self.next_seq = 0
        self.ended = False
        self.settled: str | None = None

    def made_worktree(self, clones: list[str]) -> None:
        """Record that the run's worktree is made, with the clone mechanisms it used. Refused for a
        run in the theatre, a second time, and once the runner has reported or the run ended."""
        if (self.workspace or {}).get("kind") != "worktree":
            raise _out_of_sequence(self.run_id, "a worktree was made for a run in the theatre.")
        if self.worktree_made:
            raise _out_of_sequence(self.run_id, "its worktree is already recorded as made.")
        if self.next_seq > 0 or self.ended:
            raise _out_of_sequence(
                self.run_id, "its worktree was made after its runner reported or it ended."
            )
        self._worktree_made(clones=clones)

    @event("WorktreeMade")
    def _worktree_made(self, clones: list[str]) -> None:
        self.worktree_made = True

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

    def end(
        self,
        outcome: dict[str, Any],
        recording: dict[str, Any] | None,
        changes: dict[str, Any] | None = None,
    ) -> None:
        """Record how the run ended, with a worktree run's changes. Refused if it already has."""
        if self.ended:
            raise _out_of_sequence(self.run_id, "the run's end is already recorded.")
        self._ended(outcome=outcome, recording=recording, changes=changes)

    @event("Ended")
    def _ended(
        self,
        outcome: dict[str, Any],
        recording: dict[str, Any] | None = None,
        changes: dict[str, Any] | None = None,
    ) -> None:
        self.ended = True

    def _can_settle(self) -> None:
        if not self.ended:
            raise TroupeError(
                "run.not-ended",
                problem=f"Run {self.run_id} has no recorded end, so its changes can't be settled.",
                fix=f"Wait for the run to end, then try again: troupe status {self.run_id}",
                details={"run": self.run_id},
            )
        if self.settled is not None:
            raise TroupeError(
                "run.changes-settled",
                problem=f"Run {self.run_id}'s changes were already {self.settled}.",
                fix="Nothing more can be done with them: settling a run's changes is final.",
                details={"run": self.run_id, "settled": self.settled},
            )

    def accept_changes(self, diff: str, files: list[str]) -> None:
        """Record that the run's diff was applied to the theatre. Refused before the end, and
        once the changes are settled."""
        self._can_settle()
        self._changes_accepted(diff=diff, files=files)

    @event("ChangesAccepted")
    def _changes_accepted(self, diff: str, files: list[str]) -> None:
        self.settled = "accepted"

    def discard_changes(self) -> None:
        """Record that the run's worktree was removed. Refused once the changes are settled. An
        interrupted run, which has no end, can be discarded."""
        if self.settled is not None:
            self._can_settle()
        self._changes_discarded()

    @event("ChangesDiscarded")
    def _changes_discarded(self) -> None:
        self.settled = "discarded"


STARTED = "troupe.core.runs.aggregate:Run.Started"
WORKTREE_MADE = "troupe.core.runs.aggregate:Run.WorktreeMade"
REPORTED = "troupe.core.runs.aggregate:Run.Reported"
ENDED = "troupe.core.runs.aggregate:Run.Ended"
CHANGES_ACCEPTED = "troupe.core.runs.aggregate:Run.ChangesAccepted"
CHANGES_DISCARDED = "troupe.core.runs.aggregate:Run.ChangesDiscarded"
TOPICS = (STARTED, WORKTREE_MADE, REPORTED, ENDED, CHANGES_ACCEPTED, CHANGES_DISCARDED)
"""Every topic a run records."""
