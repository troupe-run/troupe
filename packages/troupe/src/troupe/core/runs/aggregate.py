"""The run aggregate (spec: runs; perform-status-logs design D8; account-for-every-worktree
design D1 to D4).

A run is its own stream, keyed by its run id (a UUID minted by perform). Its events:

- ``Run.Started``: recorded before the run's workspace is made and its runner starts, once every
  check that can refuse the run has passed. It holds the actor's name, the runner requested, the
  stage's admission, the effect check, the direction as an artifact reference, the config version
  the run used (config-model design D14), its workspace (worktree-stage design D7), and what the
  run does when its context fills, with where that came from (compaction-opt-in design D3), and
  its step in its performance, counting from 1 (spec: performances; its lineage names the
  performance). For a
  worktree, that's where the worktree will be, so an event names it before any part of it exists.
- ``Run.WorktreeMade``: a worktree run's clone mechanisms, once its worktree is made and before its
  runner starts.
- ``Run.Reported``: one per run event, holding the runner's ``seq`` and the event as received. The
  ``seq`` is payload, never the stream's version (the library numbers versions from 1). The first
  is the runner's init, which names the runner that reported.
- ``Run.Noticed``: one per notice troupe raised for the run, holding the notice as protocol data, in
  the order troupe raised it among the run's events. Recorded by the person's command, between the
  start and the end; it has no ``seq``, which numbers only the runner's events (run-notices-in-
  history design D1, D4).
- ``Run.Ended``: the outcome the run host derived, whether recording failed part-way, and, for a
  worktree run, the changes captured from its worktree.
- ``Run.GatePassed``: troupe couldn't keep a worktree run's changes at its gate (they conflict
  with the working tree), so it passed the gate to the next approver. At most one, after the end
  and before any cue (manual-gates design D1, D4).
- ``Run.CueRaised``: the gate reached a role a person holds, with a brief. At most one.
- ``Run.ChangesAccepted``, ``Run.ChangesDiscarded`` or ``Run.ChangesRejected``: what was done with
  a worktree run's changes. At most one of them, after the end: settling is final (worktree-stage
  design D6, D7). While a cue is open, only an acceptance approved in the cue's role, or a
  rejection, settles them; a rejection needs an open cue.

A field with nothing to say (recording that didn't fail, a start with no runtime) is left
out of the stored event, so each such parameter defaults to None and the event reads back without
it (omit-nulls design D4).

The aggregate refuses a ``seq`` that isn't the next one, a report or a notice after the end, a
second end, a worktree made for a run in the theatre, twice, or after the runner reported, and a
second settling of the changes: each is a fault (a bug or a replay), never retried. The commands
that settle changes check the run first (troupe.core.runs.changes), so the aggregate's refusals are
the backstop. The topics are these classes' import paths, so this module isn't moved without
registering the old topics with the library.
"""

from typing import Any
from uuid import UUID

from eventsourcing.domain import Aggregate, event

from troupe.core import gates
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
        workspace: dict[str, Any],
        on_context_full: dict[str, Any],
        step: int,
        runtime: dict[str, Any] | None = None,
        approvers: dict[str, Any] | None = None,
    ) -> None:
        self.run_id = run_id
        self.step = step
        self.approvers = approvers
        self.runtime = runtime
        self.on_context_full = on_context_full
        self.actor = actor
        self.runner_requested = runner_requested
        self.stage = stage
        self.effect_check = effect_check
        self.direction = direction
        self.config = config
        self.workspace = workspace
        self.worktree_made = False
        self.next_seq = 0
        self.ended = False
        self.settled: str | None = None
        self.passed = False
        self.cue: str | None = None
        """The role an open cue is for; None while no cue is raised."""

    def made_worktree(self, clones: list[str]) -> None:
        """Record that the run's worktree is made, with the clone mechanisms it used. Refused for a
        run in the theatre, a second time, and once the runner has reported or the run ended."""
        if self.workspace.get("kind") != "worktree":
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

    def notice(self, notice: dict[str, Any]) -> None:
        """Record a notice troupe raised for the run (notice.schema.json data). Refused once the
        run has ended. It doesn't count as a run event: the next ``seq`` is unchanged."""
        if self.ended:
            raise _out_of_sequence(
                self.run_id, f"notice {notice.get('code')} arrived after the run ended."
            )
        self._noticed(notice=notice)

    @event("Noticed")
    def _noticed(self, notice: dict[str, Any]) -> None:
        pass

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

    def _at_gate(self, what: str) -> None:
        if not self.ended or self.settled is not None:
            raise _out_of_sequence(self.run_id, f"{what} came before its end or after it settled.")

    def pass_gate(self, approver: str, to: str, files: list[str]) -> None:
        """Record that ``approver`` couldn't keep the changes (``files`` conflict) and passed the
        gate to ``to``. Only troupe passes, once, before any cue."""
        self._at_gate("a pass")
        if self.passed or self.cue is not None or approver != gates.TROUPE:
            raise _out_of_sequence(self.run_id, f"{approver} passed its gate out of turn.")
        self._gate_passed(approver=approver, to=to, reason="conflict", files=files)

    @event("GatePassed")
    def _gate_passed(self, approver: str, to: str, reason: str, files: list[str]) -> None:
        self.passed = True

    def raise_cue(self, role: str, brief: dict[str, Any]) -> None:
        """Record a cue for ``role``, with its brief. Once, after the end and before settling."""
        self._at_gate("a cue")
        if self.cue is not None:
            raise _out_of_sequence(self.run_id, "its cue is already raised.")
        self._cue_raised(role=role, brief=brief)

    @event("CueRaised")
    def _cue_raised(self, role: str, brief: dict[str, Any]) -> None:
        self.cue = role

    def accept_changes(
        self, diff: str, files: list[str], *, approved_as: str | None = None
    ) -> None:
        """Record that the run's diff was applied to the theatre. Refused before the end, once
        the changes are settled, and while a cue is open unless approved in its role
        (``approved_as``: the role of the approval the acceptance's lineage carries)."""
        self._can_settle()
        if self.cue is not None and approved_as != self.cue:
            raise gates.waiting_at_gate(self.run_id, self.cue, discarding=False)
        self._changes_accepted(diff=diff, files=files)

    @event("ChangesAccepted")
    def _changes_accepted(self, diff: str, files: list[str]) -> None:
        self.settled = "accepted"

    def discard_changes(self) -> None:
        """Record that the run's worktree was removed. Refused once the changes are settled. An
        interrupted run, which has no end, can be discarded."""
        if self.settled is not None:
            self._can_settle()
        if self.cue is not None:
            raise gates.waiting_at_gate(self.run_id, self.cue, discarding=True)
        self._changes_discarded()

    @event("ChangesDiscarded")
    def _changes_discarded(self) -> None:
        self.settled = "discarded"

    def reject_changes(self, role: str) -> None:
        """Record that the open cue's role rejected the changes. Needs an open cue for ``role``."""
        self._can_settle()
        if self.cue != role:
            raise gates.no_cue(self.run_id, "pending")
        self._changes_rejected(role=role)

    @event("ChangesRejected")
    def _changes_rejected(self, role: str) -> None:
        self.settled = "rejected"


STARTED = "troupe.core.runs.aggregate:Run.Started"
WORKTREE_MADE = "troupe.core.runs.aggregate:Run.WorktreeMade"
REPORTED = "troupe.core.runs.aggregate:Run.Reported"
NOTICED = "troupe.core.runs.aggregate:Run.Noticed"
ENDED = "troupe.core.runs.aggregate:Run.Ended"
CHANGES_ACCEPTED = "troupe.core.runs.aggregate:Run.ChangesAccepted"
CHANGES_DISCARDED = "troupe.core.runs.aggregate:Run.ChangesDiscarded"
GATE_PASSED = "troupe.core.runs.aggregate:Run.GatePassed"
CUE_RAISED = "troupe.core.runs.aggregate:Run.CueRaised"
CHANGES_REJECTED = "troupe.core.runs.aggregate:Run.ChangesRejected"
TOPICS = (
    STARTED,
    WORKTREE_MADE,
    REPORTED,
    NOTICED,
    ENDED,
    CHANGES_ACCEPTED,
    CHANGES_DISCARDED,
    GATE_PASSED,
    CUE_RAISED,
    CHANGES_REJECTED,
)
"""Every topic a run records."""
