"""Reading runs back: a performance id names its run, a prefix matching a run and a performance is
ambiguous, a performance with several runs is refused, and a run recorded before performances is
refused with the files that hold it (spec: performances, runs; performances design D6, D8)."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from protocol_guard import unchecked
from runtesting import PERFORMANCE, STAGE
from storetesting import Counter, files_service
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.runs.aggregate import Run
from troupe.core.runs.projections import RunView
from troupe.core.runs.queries import read_runs, resolve


def view(run_id: str, performance: str | None) -> RunView:
    return RunView(run_id=run_id, started={"actor": "tester"}, performance=performance)


RUN = "1a2b3c4d-0000-4000-8000-000000000001"
OTHER = "5e6f7a8b-0000-4000-8000-000000000002"


def test_a_performances_full_id_names_its_one_run() -> None:
    runs = {RUN: view(RUN, PERFORMANCE)}
    assert resolve(PERFORMANCE, runs) == RUN


def test_a_prefix_of_a_performance_names_its_one_run() -> None:
    runs = {RUN: view(RUN, PERFORMANCE)}
    assert resolve(PERFORMANCE[:8], runs) == RUN


def test_a_run_id_still_names_the_run() -> None:
    runs = {RUN: view(RUN, PERFORMANCE)}
    assert resolve(RUN, runs) == RUN
    assert resolve(RUN[:8], runs) == RUN


def test_a_prefix_matching_a_run_and_another_performance_is_ambiguous_listing_both() -> None:
    performance = "1a2b3c4d-0000-4000-8000-00000000000f"
    runs = {RUN: view(RUN, PERFORMANCE), OTHER: view(OTHER, performance)}
    with pytest.raises(TroupeError) as caught:
        resolve("1a2b3c4d", runs)
    assert caught.value.code == "run.ambiguous-id"
    assert caught.value.details["matches"] == sorted([RUN, performance])


def test_a_performance_with_several_runs_is_refused_listing_them() -> None:
    runs = {RUN: view(RUN, PERFORMANCE), OTHER: view(OTHER, PERFORMANCE)}
    with pytest.raises(TroupeError) as caught:
        resolve(PERFORMANCE, runs)
    assert caught.value.code == "performance.several-runs"
    assert caught.value.details == {"performance": PERFORMANCE, "runs": [RUN, OTHER]}


def test_an_id_that_matches_nothing_is_not_found() -> None:
    with pytest.raises(TroupeError) as caught:
        resolve("deadbeef", {RUN: view(RUN, PERFORMANCE)})
    assert caught.value.code == "run.not-found"


def _record_an_old_run(store: EventStore, run_id: str) -> None:
    """A run's start as a troupe before performances recorded it: no performance in its lineage.
    The service refuses to record that now, so it goes to the store's recorder directly."""
    run = Run(
        run_id=run_id,
        actor="tester",
        runner_requested="scripted",
        stage=STAGE,
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=["sha256:" + "b" * 64],
        workspace={"kind": "theatre"},
        on_context_full={"value": "fail", "source": "default"},
        step=1,
    )
    lineage = store.command(via="cli").lineage().to_data()
    with unchecked():  # invalid on purpose: an older troupe's record
        stored = [store._stored(event, lineage) for event in run.collect_events()]
    store.recorder.insert(stored)


def _record_a_new_run(store: EventStore) -> None:
    run = Run(
        run_id=str(uuid4()),
        actor="tester",
        runner_requested="scripted",
        stage=STAGE,
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=["sha256:" + "b" * 64],
        workspace={"kind": "theatre"},
        on_context_full={"value": "fail", "source": "default"},
        step=1,
    )
    store.command(via="cli", performance=PERFORMANCE).record(run.collect_events())


def _segment_of(store: EventStore, run_id: str) -> str:
    [path] = {event.path for event in store.history(UUID(run_id))}
    return path.resolve().relative_to(store.theatre.resolve()).as_posix()


def test_a_run_from_before_performances_alone_in_its_file_is_refused_naming_it_to_remove(
    tmp_path: Path,
) -> None:
    _record_a_new_run(files_service(tmp_path))
    old = str(uuid4())
    store = files_service(tmp_path)
    _record_an_old_run(store, old)
    with pytest.raises(TroupeError) as caught:
        read_runs(files_service(tmp_path))
    error = caught.value
    assert error.code == "run.recorded-before-performances"
    segment = _segment_of(store, old)
    assert error.details == {"runs": [old], "remove": [segment], "keep": []}
    assert old[:8] in error.problem
    assert "troupe-run<0.5" in error.fix
    assert segment in error.fix


def test_a_run_from_before_performances_sharing_a_file_names_that_file_to_keep(
    tmp_path: Path,
) -> None:
    store = files_service(tmp_path)
    store.command(via="cli").record(Counter(value=1).collect_events())
    old = str(uuid4())
    _record_an_old_run(store, old)
    with pytest.raises(TroupeError) as caught:
        read_runs(files_service(tmp_path))
    error = caught.value
    assert error.code == "run.recorded-before-performances"
    segment = _segment_of(store, old)
    assert error.details == {"runs": [old], "remove": [], "keep": [segment]}
    assert f"Keep {segment}" in error.fix


def test_runs_that_name_their_performance_read_back_with_it(tmp_path: Path) -> None:
    store = files_service(tmp_path)
    _record_a_new_run(store)
    [found] = read_runs(store).values()
    assert found.performance == PERFORMANCE
