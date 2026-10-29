"""The runs projections: pure folds over recorded run events (spec: runs; perform-status-logs
design D12).

Each fold takes one recorded event at a time (its topic, its state and its lineage), so a query can
rebuild what it needs from the store, and a later follower can run the same fold and keep its
position in the store's tracking log. A run's state isn't recorded; it is derived (design D11),
so the summary takes it as an argument. So is the state of a worktree run's changes
(worktree-stage design D7): pending, accepted, discarded, none or uncaptured.

A run's reported runner is read from its init, its first reported event, and a worktree's clone
mechanisms from Run.WorktreeMade. A start an older troupe recorded holds both itself, and they're
read from there (account-for-every-worktree design D3, D4, D7).
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
    ENDED,
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
    ended: dict[str, Any] | None = None
    ended_at: str | None = None
    settled: str | None = None
    settled_at: str | None = None
    log: list[m.LoggedEvent] = field(default_factory=list)

    def apply(self, recording: Recording, *, keep_log: bool) -> None:
        state = _state(recording)
        if recording.topic == STARTED:
            self.started = state
            self.started_by = (recording.lineage or {}).get("actor")
            self.started_at = _at(recording)
        elif recording.topic == WORKTREE_MADE:
            self.clones = state["clones"]
        elif recording.topic == REPORTED:
            self.events += 1
            event = state["event"]
            if state["seq"] == 0 and event.get("type") == "init":
                runner = event["runner"]
                self.reported = {"name": runner["name"], "version": runner["version"]}
            if keep_log:
                self.log.append(logged(self.run_id, state, _at(recording)))
        elif recording.topic == ENDED:
            self.ended = state
            self.ended_at = _at(recording)
        elif recording.topic in (CHANGES_ACCEPTED, CHANGES_DISCARDED):
            self.settled = "accepted" if recording.topic == CHANGES_ACCEPTED else "discarded"
            self.settled_at = _at(recording)

    @property
    def workspace(self) -> dict[str, Any]:
        """The run's workspace as its start recorded it, with a worktree's clone mechanisms once
        it is made; a run recorded before runs had workspaces worked in the theatre."""
        recorded = (self.started or {}).get("workspace")
        if not isinstance(recorded, dict):
            return {"kind": "theatre"}
        if self.clones is not None and "clones" not in recorded:
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
            return data
        data["worktree"] = workspace["path"]
        if self.captured is None or "error" in captured:
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
            "actor": started["actor"],
            "startedBy": self.started_by,
            "runner": _present(
                {
                    "requested": started["runner_requested"],
                    "reported": started.get("runner_reported") or self.reported,
                }
            ),
            "stage": started["stage"],
            "effectCheck": started["effect_check"],
            "workspace": self.workspace,
            "state": state,
            "outcome": outcome.get("outcome"),
            "error": outcome.get("error"),
            "events": self.events,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "transcript": outcome.get("transcript"),
            "stderr": outcome.get("stderr"),
            "recording": (self.ended or {}).get("recording"),
            "changes": self.changes(),
        }
        return m.RunSummary.from_data(_present(summary))


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
