"""The performance aggregate records its start and one end, refuses a second end, and works out its
outcome from its run's (spec: performances; performances design D1, D3)."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from storetesting import files_service, snapshot
from troupe.core.errors import TroupeError
from troupe.core.runs.performance import ENDED, STARTED, Performance, outcome_of


def new_performance(performance_id: str | None = None) -> Performance:
    return Performance(
        performance_id=performance_id or str(uuid4()),
        performed={"kind": "actor", "name": "tester"},
        steps=[
            {"actor": "tester", "approvers": {"value": ["troupe", "director"], "source": "default"}}
        ],
        direction="sha256:" + "a" * 64,
        config=["sha256:" + "b" * 64],
    )


def test_a_performance_records_its_start_and_its_end_naming_itself(tmp_path: Path) -> None:
    store = files_service(tmp_path)
    performance = new_performance()
    performance.end("completed")
    command = store.command(via="cli", performance=performance.performance_id)
    command.record(performance.collect_events())
    history = store.history(UUID(performance.performance_id))
    assert [event.topic for event in history] == [STARTED, ENDED]
    assert all(
        e.lineage and e.lineage["performance"] == performance.performance_id for e in history
    )
    loaded = store.load(UUID(performance.performance_id))
    assert isinstance(loaded, Performance)
    assert loaded.outcome == "completed"
    assert loaded.steps == performance.steps


def test_a_second_end_is_refused_as_a_fault_and_writes_nothing(tmp_path: Path) -> None:
    store = files_service(tmp_path)
    performance = new_performance()
    performance.end("failed")
    command = store.command(via="cli", performance=performance.performance_id)
    command.record(performance.collect_events())
    before = snapshot(tmp_path)
    with pytest.raises(TroupeError) as caught:
        performance.end("completed")
    assert caught.value.code == "performance.out-of-sequence"
    assert caught.value.details == {"performance": performance.performance_id}
    assert performance.collect_events() == []
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    ("run_outcome", "expected"),
    [
        ("succeeded", "completed"),
        ("cancelled", "cancelled"),
        ("failed", "failed"),
        ("timed-out", "failed"),
        ("crashed", "failed"),
        ("could-not-start", "failed"),
    ],
)
def test_a_performances_outcome_follows_its_runs(run_outcome: str, expected: str) -> None:
    assert outcome_of(run_outcome) == expected


def test_a_run_that_succeeded_but_whose_changes_werent_captured_fails_its_performance() -> None:
    error = {"code": "vcs.failed", "problem": "p", "fix": "f"}
    assert outcome_of("succeeded", {"error": error}) == "failed"
    assert outcome_of("succeeded", {"diff": "sha256:" + "a" * 64}) == "completed"
