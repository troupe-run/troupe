"""The run aggregate refuses a run event out of sequence (spec: runs; perform-status-logs design
D8)."""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from storetesting import files_service, snapshot
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.runners.limits import RunLimits
from troupe.core.runs.aggregate import ENDED, REPORTED, STARTED, Run


def outcome(name: str) -> dict[str, Any]:
    """An outcome as the run host derives it (Run.Ended's schema), for a run that ended ``name``."""
    return {
        "outcome": name,
        "exitCode": 0,
        "ending": "exited",
        "transcript": "sha256:" + "a" * 64,
        "stderr": "sha256:" + "b" * 64,
        "limits": RunLimits().to_data(),
    }


STAGE = {
    "name": "local",
    "effects": "unenforced",
    "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
}


def new_run(run_id: str | None = None) -> Run:
    return Run(
        run_id=run_id or str(uuid4()),
        actor="tester",
        runner_requested="scripted",
        runner_reported={"name": "scripted", "version": "0.1.0"},
        stage=STAGE,
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=["sha256:" + "b" * 64],
    )


def log(run: Run, seq: int) -> dict[str, Any]:
    return {"runId": run.run_id, "seq": seq, "type": "log", "level": "info", "message": str(seq)}


def recorded(tmp_path: Path) -> tuple[EventStore, Run]:
    """A run whose start and first two events are recorded."""
    store = files_service(tmp_path)
    run = new_run()
    run.report(0, log(run, 0))
    run.report(1, log(run, 1))
    store.command(via="runner").record(run.collect_events())
    return store, run


@pytest.mark.parametrize(
    ("seq", "expected"), [(1, 2), (0, 2), (3, 2), (5, 2)], ids=["repeat", "replay", "gap", "jump"]
)
def test_a_seq_that_isnt_the_next_is_refused_and_nothing_is_written(
    tmp_path: Path, seq: int, expected: int
) -> None:
    _, run = recorded(tmp_path)
    before = snapshot(tmp_path)
    with pytest.raises(TroupeError) as caught:
        run.report(seq, log(run, seq))
    assert caught.value.code == "run.out-of-sequence"
    assert caught.value.details == {"run": run.run_id, "seq": seq, "expected": expected}
    assert run.collect_events() == []
    assert snapshot(tmp_path) == before


def test_an_event_whose_own_seq_disagrees_with_the_report_is_refused(tmp_path: Path) -> None:
    _, run = recorded(tmp_path)
    with pytest.raises(TroupeError) as caught:
        run.report(2, log(run, 3))
    assert caught.value.code == "run.out-of-sequence"


def test_a_report_after_the_end_is_refused(tmp_path: Path) -> None:
    _, run = recorded(tmp_path)
    run.end(outcome("succeeded"), None)
    run.collect_events()
    with pytest.raises(TroupeError) as caught:
        run.report(2, log(run, 2))
    assert caught.value.code == "run.out-of-sequence"
    assert "after the run ended" in caught.value.problem


def test_a_second_end_is_refused(tmp_path: Path) -> None:
    _, run = recorded(tmp_path)
    run.end(outcome("succeeded"), None)
    run.collect_events()
    with pytest.raises(TroupeError) as caught:
        run.end(outcome("failed"), None)
    assert caught.value.code == "run.out-of-sequence"


def test_a_second_start_for_a_recorded_run_is_refused_by_the_store_and_writes_nothing(
    tmp_path: Path,
) -> None:
    store, run = recorded(tmp_path)
    before = snapshot(tmp_path)
    with pytest.raises(TroupeError) as caught:
        store.command(via="runner").record(new_run(run.run_id).collect_events())
    assert caught.value.code == "events.version-conflict"
    assert snapshot(tmp_path) == before


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(count=st.integers(0, 12), end=st.booleans())
def test_any_gap_free_sequence_is_accepted_and_reads_back_in_order(
    tmp_path_factory: pytest.TempPathFactory, count: int, end: bool
) -> None:
    store = files_service(tmp_path_factory.mktemp("run"))
    run = new_run()
    store.command(via="cli").record(run.collect_events())
    for seq in range(count):
        run.report(seq, log(run, seq))
        store.command(via="runner").record(run.collect_events())
    if end:
        run.end(outcome("succeeded"), None)
        store.command(via="runner").record(run.collect_events())
    history = store.history(UUID(run.run_id))
    assert [r.topic for r in history] == [STARTED, *[REPORTED] * count, *([ENDED] if end else [])]
    assert [r.version for r in history] == list(range(1, len(history) + 1))
    loaded = store.load(UUID(run.run_id))
    assert isinstance(loaded, Run)
    assert loaded.next_seq == count
    assert loaded.ended is end
