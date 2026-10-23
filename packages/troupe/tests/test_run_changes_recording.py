"""Recording a worktree run's workspace and changes, settling them, and deriving their state
(spec: runs, run-workspaces, client-protocol; worktree-stage design D7)."""

import copy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from protocol_schemas import PROTOCOL_BASE, validator_for
from storetesting import files_service
from test_run_aggregate import STAGE, outcome
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.runs.aggregate import Run
from troupe.core.runs.projections import fold_runs

BASE = "c0ffee" + "0" * 34
DIFF = "sha256:" + "d" * 64
PATH = ".troupe/local/worktrees/run"
WORKTREE: dict[str, Any] = {
    "kind": "worktree",
    "path": PATH,
    "base": BASE,
    "dirty": False,
    "clones": ["clonefile"],
}
CAPTURED: dict[str, Any] = {"diff": DIFF, "added": 1, "modified": 1, "deleted": 0, "leftOut": 0}
ENDED = validator_for(PROTOCOL_BASE + "events/run-ended.schema.json")
STARTED = validator_for(PROTOCOL_BASE + "events/run-started.schema.json")


def new_run(workspace: dict[str, Any] | None = WORKTREE) -> Run:
    return Run(
        run_id=str(uuid4()),
        actor="tester",
        runner_requested="scripted",
        stage=STAGE,
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=["sha256:" + "b" * 64],
        workspace=workspace,
    )


def record(store: EventStore, run: Run) -> None:
    store.command(via="cli").record(run.collect_events())


def changes_of(store: EventStore, run: Run) -> dict[str, Any] | None:
    [view] = fold_runs(store.history(UUID(run.run_id))).values()
    return view.changes()


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    return files_service(tmp_path)


# Requirement: Accepting and discarding are recorded, and final


def test_accepting_before_the_end_is_refused_as_not_ended(store: EventStore) -> None:
    run = new_run()
    with pytest.raises(TroupeError) as caught:
        run.accept_changes(DIFF, ["a.txt"])
    assert caught.value.code == "run.not-ended"


def test_a_second_settling_is_refused_naming_the_first(store: EventStore) -> None:
    run = new_run()
    run.end(outcome("succeeded"), None, CAPTURED)
    run.discard_changes()
    with pytest.raises(TroupeError) as caught:
        run.accept_changes(DIFF, ["a.txt"])
    assert caught.value.code == "run.changes-settled"
    assert caught.value.details["settled"] == "discarded"
    with pytest.raises(TroupeError):
        run.discard_changes()


def test_an_interrupted_run_with_no_end_can_be_discarded(store: EventStore) -> None:
    run = new_run()
    record(store, run)
    run.discard_changes()
    record(store, run)
    assert (changes_of(store, run) or {})["state"] == "discarded"


def test_settling_events_validate_and_read_back_in_the_runs_stream(store: EventStore) -> None:
    run = new_run()
    run.end(outcome("succeeded"), None, CAPTURED)
    run.accept_changes(DIFF, ["out/hello.txt", "src/a.txt"])
    record(store, run)  # the protocol guard checks each payload against its topic's schema
    topics = [event.topic.split(":")[1] for event in store.history(UUID(run.run_id))]
    assert topics == ["Run.Started", "Run.Ended", "Run.ChangesAccepted"]


# Requirement: A run's changes have a state


@pytest.mark.parametrize(
    ("captured", "expected"),
    [
        (CAPTURED, "pending"),
        ({"added": 0, "modified": 0, "deleted": 0, "leftOut": 0}, "none"),
        (
            {
                "error": {
                    "code": "vcs.failed",
                    "problem": "p",
                    "fix": "f",
                    "details": {"command": "git diff", "exitStatus": 128},
                }
            },
            "uncaptured",
        ),
    ],
    ids=["pending", "none", "capture failed"],
)
def test_an_ended_worktree_runs_changes_are_in_the_state_its_end_recorded(
    store: EventStore, captured: dict[str, Any], expected: str
) -> None:
    run = new_run()
    run.end(outcome("succeeded"), None, captured)
    record(store, run)
    changes = changes_of(store, run)
    assert changes is not None
    assert changes["state"] == expected
    assert changes["worktree"] == PATH
    assert ("diff" in changes) == (expected == "pending")


def test_a_worktree_run_with_no_end_has_uncaptured_changes(store: EventStore) -> None:
    run = new_run()
    record(store, run)
    assert changes_of(store, run) == {"state": "uncaptured", "worktree": PATH}


def test_accepted_changes_keep_the_counts_name_when_and_drop_the_worktree(
    store: EventStore,
) -> None:
    run = new_run()
    run.end(outcome("succeeded"), None, CAPTURED)
    run.accept_changes(DIFF, ["a.txt"])
    record(store, run)
    changes = changes_of(store, run) or {}
    assert changes["state"] == "accepted"
    assert changes["diff"] == DIFF
    assert "settledAt" in changes
    assert "worktree" not in changes


def test_a_run_in_the_theatre_has_no_changes(store: EventStore) -> None:
    run = new_run({"kind": "theatre"})
    run.end(outcome("succeeded"), None)
    record(store, run)
    assert changes_of(store, run) is None


def test_a_run_recorded_before_workspaces_reads_back_as_in_the_theatre(store: EventStore) -> None:
    run = new_run(None)  # leaves workspace out, as every run recorded before this change did
    record(store, run)
    [view] = fold_runs(store.history(UUID(run.run_id))).values()
    assert view.workspace == {"kind": "theatre"}
    assert view.changes() is None


# The event schemas refuse what contradicts itself


def _ended(changes: dict[str, Any]) -> dict[str, Any]:
    return {
        "lineage": {},
        "timestamp": {"_type_": "datetime_iso", "_data_": "2026-10-12T03:04:05.678000+00:00"},
        "outcome": outcome("succeeded"),
        "changes": changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param(
            {**CAPTURED, "error": {"code": "vcs.failed", "problem": "p", "fix": "f"}},
            id="a diff and an error",
        ),
        pytest.param(
            {k: v for k, v in CAPTURED.items() if k != "diff"}, id="files changed and no diff"
        ),
        pytest.param(
            {"diff": DIFF, "added": 0, "modified": 0, "deleted": 0, "leftOut": 0},
            id="a diff with nothing changed",
        ),
        pytest.param({**CAPTURED, "shared": {}}, id="shared changes that name nothing"),
        pytest.param({**CAPTURED, "diff": None}, id="a null diff"),
    ],
)
def test_changes_that_contradict_themselves_dont_validate(changes: dict[str, Any]) -> None:
    errors = [e.message for e in ENDED.iter_errors(_ended(changes)) if "lineage" not in e.message]
    assert errors


def test_real_captured_changes_validate_apart_from_the_lineage() -> None:
    data = _ended({**CAPTURED, "shared": {"hooks": [{"name": "pre-commit", "change": "added"}]}})
    paths = {tuple(e.absolute_path)[:1] for e in ENDED.iter_errors(data)}
    assert paths <= {("lineage",)}


def test_a_worktree_workspace_without_a_base_doesnt_validate() -> None:
    workspace = copy.deepcopy(WORKTREE)
    del workspace["base"]
    errors = list(STARTED.iter_errors({"workspace": workspace}))
    assert any(tuple(e.absolute_path)[:1] == ("workspace",) for e in errors) or any(
        "workspace" in str(e.schema_path) for e in errors
    )
