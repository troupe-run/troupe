"""The runs projections: pure folds over recorded run events (spec: runs; perform-status-logs
design D12).

Each fold takes one recorded event at a time (its topic, its state and its lineage), so a query can
rebuild what it needs from the store, and a later follower can run the same fold and keep its
position in the store's tracking log. A run's state isn't recorded; it is derived (design D11),
so the summary takes it as an argument. So is the state of a worktree run's changes
(worktree-stage design D7): pending, accepted, discarded, none or uncaptured.

A run's reported runner is read from its init, its first reported event, and a worktree's clone
mechanisms from Run.WorktreeMade (account-for-every-worktree design D3, D4, D7;
require-always-written-fields design D2, D3).

A run's usage and cost are read from its result, once it is recorded (run-usage-display D2).

A run's recorded notices are kept always, since a run has few, and in its log among its events in
the order they were recorded (run-notices-in-history design D8).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from troupe.core import strict_json
from troupe.core.client import messages as m
from troupe.core.runs.aggregate import (
    CHANGES_ACCEPTED,
    CHANGES_DISCARDED,
    CHANGES_REJECTED,
    CUE_RAISED,
    ENDED,
    GATE_PASSED,
    NOTICED,
    REPORTED,
    STARTED,
    WORKTREE_MADE,
)


class Recording(Protocol):
    """What a fold needs of a recorded event."""

    @property
    def stream(self) -> UUID | str: ...
    @property
    def topic(self) -> str: ...
    @property
    def state(self) -> bytes: ...
    @property
    def lineage(self) -> dict[str, Any] | None: ...


def _state(recording: Recording) -> dict[str, Any]:
    state = strict_json.loads(recording.state)
    if not isinstance(state, dict):
        raise TypeError("a run event's state is a JSON object")
    return state


def _at(recording: Recording) -> str:
    lineage = recording.lineage or {}
    at = lineage.get("at")
    if not isinstance(at, str):
        raise TypeError("a run event troupe recorded carries its lineage time")
    return at


@dataclass
class RunView:
    """What the runs projection knows about one run."""

    run_id: str
    started: dict[str, Any] | None = None
    started_by: dict[str, Any] | None = None
    started_at: str | None = None
    events: int = 0
    reported: dict[str, Any] | None = None
    clones: list[str] | None = None
    usage: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None
    ended: dict[str, Any] | None = None
    ended_at: str | None = None
    settled: str | None = None
    settled_at: str | None = None
    notices: list[m.RunNotice] = field(default_factory=list)
    log: list[m.LogEntry] = field(default_factory=list)
    gate: list[dict[str, Any]] = field(default_factory=list)
    """The gate's steps, in recorded order, as gateStep data (manual-gates design D6)."""
    cue: dict[str, Any] | None = None
    """The cue raised at the gate: its role and when."""
    kept_files: list[str] | None = None
    """The files an acceptance changed."""
    performance: str | None = None
    """The performance the run is a step of, from its start's lineage (spec: performances). None
    only for a run recorded before performances, which reading runs back refuses (performances
    design D8)."""

    def apply(self, recording: Recording, *, keep_log: bool) -> None:
        state = _state(recording)
        if recording.topic == STARTED:
            self.started = state
            self.started_by = (recording.lineage or {}).get("actor")
            self.started_at = _at(recording)
            self.performance = (recording.lineage or {}).get("performance")
        elif recording.topic == WORKTREE_MADE:
            self.clones = state["clones"]
        elif recording.topic == REPORTED:
            self.events += 1
            event = state["event"]
            if state["seq"] == 0 and event.get("type") == "init":
                runner = event["runner"]
                self.reported = {"name": runner["name"], "version": runner["version"]}
            elif event.get("type") == "result":
                self.usage, self.cost = _usage_and_cost(event)
            if keep_log:
                self.log.append(logged(self.run_id, state, _at(recording)))
        elif recording.topic == NOTICED:
            at = _at(recording)
            notice = m.NoticeData.from_data(state["notice"])
            self.notices.append(m.RunNotice(at=at, notice=notice))
            if keep_log:
                self.log.append(m.LoggedNotice(run_id=self.run_id, at=at, notice=notice))
        elif recording.topic == ENDED:
            self.ended = state
            self.ended_at = _at(recording)
        elif recording.topic == GATE_PASSED:
            self.gate.append(
                {
                    "step": "passed",
                    "approver": state["approver"],
                    "to": state["to"],
                    "files": state["files"],
                    "at": _at(recording),
                }
            )
        elif recording.topic == CUE_RAISED:
            self.cue = {"role": state["role"], "raisedAt": _at(recording)}
            self.gate.append({"step": "cue", "role": state["role"], "at": _at(recording)})
        elif recording.topic in (CHANGES_ACCEPTED, CHANGES_DISCARDED, CHANGES_REJECTED):
            self.settled = {
                CHANGES_ACCEPTED: "accepted",
                CHANGES_DISCARDED: "discarded",
                CHANGES_REJECTED: "rejected",
            }[recording.topic]
            self.settled_at = _at(recording)
            self.kept_files = state.get("files")
            self._answered(recording, state)

    def _answered(self, recording: Recording, state: dict[str, Any]) -> None:
        """The gate's answer, when the settling event is one: an acceptance whose lineage carries
        an approval, or a rejection."""
        lineage = recording.lineage or {}
        if recording.topic == CHANGES_ACCEPTED:
            approvals = lineage.get("approvals") or []
            if not approvals:
                return
            role, step = approvals[0]["role"], "approved"
        elif recording.topic == CHANGES_REJECTED:
            role, step = state["role"], "rejected"
        else:
            return
        self.gate.append(
            _present(
                {
                    "step": step,
                    "role": role,
                    "actor": lineage.get("actor"),
                    "reason": lineage.get("reason"),
                    "at": _at(recording),
                }
            )
        )

    @property
    def workspace(self) -> dict[str, Any]:
        """The run's workspace as its start recorded it, with a worktree's clone mechanisms once
        it is made."""
        if self.started is None:
            raise ValueError(f"run {self.run_id} has no recorded start to read its workspace from")
        recorded: dict[str, Any] = self.started["workspace"]
        if self.clones is not None:
            return {**recorded, "clones": self.clones}
        return recorded

    @property
    def captured(self) -> dict[str, Any] | None:
        """The changes the run's end recorded, if it has an end that recorded any."""
        changes = (self.ended or {}).get("changes")
        return changes if isinstance(changes, dict) else None

    def changes(self) -> dict[str, Any] | None:
        """A worktree run's changes and their state; None for a run in the theatre."""
        workspace = self.workspace
        if workspace.get("kind") != "worktree":
            return None
        captured = self.captured or {}
        data: dict[str, Any] = {
            key: captured[key]
            for key in ("diff", "added", "modified", "deleted", "leftOut", "shared", "error")
            if key in captured
        }
        if self.settled is not None:
            data["state"] = self.settled
            data["settledAt"] = self.settled_at
            if self.kept_files:
                data["files"] = self.kept_files
            return data
        data["worktree"] = workspace["path"]
        if self.cue is not None:
            data["state"] = "waiting"
            data["cue"] = self.cue
        elif self.captured is None or "error" in captured:
            data["state"] = "uncaptured"
        else:
            data["state"] = "pending" if "diff" in captured else "none"
        return data

    @property
    def visible(self) -> bool:
        """Whether the run's start is recorded: a run without one isn't shown yet."""
        return self.started is not None

    def summary(self, state: m.State) -> m.RunSummary:
        if self.started is None or self.started_by is None or self.started_at is None:
            raise ValueError(f"run {self.run_id} has no recorded start to summarise")
        started = self.started
        outcome: dict[str, Any] = (self.ended or {}).get("outcome") or {}
        summary = {
            "runId": self.run_id,
            "performanceId": self.performance,
            "step": started.get("step"),
            "actor": started["actor"],
            "startedBy": self.started_by,
            "runner": _present(
                {
                    "requested": started["runner_requested"],
                    "reported": self.reported,
                }
            ),
            "stage": started["stage"],
            "effectCheck": started["effect_check"],
            "workspace": self.workspace,
            "state": state,
            "outcome": outcome.get("outcome"),
            "error": outcome.get("error"),
            "audit": outcome.get("audit"),
            "events": self.events,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "transcript": outcome.get("transcript"),
            "transcriptFormat": outcome.get("transcriptFormat"),
            "stderr": outcome.get("stderr"),
            "recording": (self.ended or {}).get("recording"),
            "notices": [notice.to_data() for notice in self.notices] or None,
            "changes": self.changes(),
            "usage": self.usage,
            "cost": self.cost,
            "approvers": started.get("approvers"),
            "gate": list(self.gate) or None,
        }
        return m.RunSummary.from_data(_present(summary))

    def open_cue(self) -> m.OpenCue | None:
        """The run's open cue, as status lists it; None when nothing waits at its gate."""
        if self.cue is None or self.settled is not None or self.started is None:
            return None
        return m.OpenCue(
            run=self.run_id,
            actor=self.started["actor"],
            role=self.cue["role"],
            raised_at=self.cue["raisedAt"],
        )


def _usage_and_cost(
    result: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """A result event's usage, as it carries it, and its cost with the kind of figure it is:
    ``costUsd`` is reported, ``estimatedCostUsd`` estimated, and a result carries one or neither
    (run-usage-display D1, D2)."""
    cost = None
    if "costUsd" in result:
        cost = {"usd": result["costUsd"], "kind": "reported"}
    elif "estimatedCostUsd" in result:
        cost = {"usd": result["estimatedCostUsd"], "kind": "estimated"}
    return result.get("usage"), cost


def _present(data: dict[str, Any]) -> dict[str, Any]:
    """``data`` without the fields that have nothing to say: absent, never null (omit-nulls)."""
    return {key: value for key, value in data.items() if value is not None}


def logged(run_id: str, reported: Mapping[str, Any], at: str) -> m.LoggedEvent:
    """A Run.Reported event's state as a logged event."""
    return m.LoggedEvent.from_data(
        {
            "kind": "event",
            "runId": run_id,
            "seq": reported["seq"],
            "at": at,
            "event": reported["event"],
        }
    )


def run_id_of(recording: Recording) -> str:
    return str(UUID(str(recording.stream)))


def fold_runs(recordings: Iterable[Recording], *, keep_log: bool = False) -> dict[str, RunView]:
    """Every run in ``recordings``, in the order each was first seen."""
    runs: dict[str, RunView] = {}
    for recording in recordings:
        run_id = run_id_of(recording)
        runs.setdefault(run_id, RunView(run_id)).apply(recording, keep_log=keep_log)
    return runs
