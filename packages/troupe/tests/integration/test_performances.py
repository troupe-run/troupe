"""Every perform records a performance: its start in the same batch as its run's, every event of
both naming it, and its end in the same batch as whatever settles it (spec: performances, lineage;
performances design D2 to D4)."""

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from event_service_shared import recorded_lines
from gitrepo import Repo
from run_workspaces_shared import Recording, configured, write
from runtesting import INIT, OK, Harness, committed, request, script, theatre
from troupe.core.client import messages as m
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.runners.limits import RunLimits
from troupe.core.runs import gate
from troupe.core.runs.changes import accept, discard
from troupe.core.runs.performance import ENDED, STARTED

FAIL = {"event": {"type": "result", "status": "error", "reason": "other", "message": "no"}}
EVERYWHERE = {"write": ["**"]}


def performance_events(made: Harness, performance: str) -> list[tuple[str, dict[str, Any]]]:
    """The performance's stream: each event's topic and its line as recorded."""
    lines = {line["id"]: line for line in recorded_lines(made.repo.path)}
    store = made.backends().event_store(made.session())
    return [(event.topic, lines[event.id]) for event in store.history(UUID(performance))]


def run_lines(made: Harness, run_id: str) -> list[dict[str, Any]]:
    lines = {line["id"]: line for line in recorded_lines(made.repo.path)}
    store = made.backends().event_store(made.session())
    return [lines[event.id] for event in store.history(UUID(run_id))]


def call(made: Harness, handler: Any, request_: Any) -> Any:  # noqa: ANN401
    return asyncio.run(handler(request_, made.session(), made.send, backends=made.backends()))


def gated(
    made: Harness, *steps: dict[str, Any], approvers: list[str] | None = None
) -> m.RunSummary:
    fields: dict[str, Any] = {"effects": EVERYWHERE}
    if approvers is not None:
        fields["approvers"] = approvers
    return made.perform(configured(made, INIT, *steps, **fields)).run


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return committed(tmp_path)


# Requirement: Every perform records a performance; A performance's start is recorded with its
# first run's start; A run's start names its step


def test_a_performs_performance_starts_in_its_runs_start_batch_naming_one_step(
    tmp_path: Path,
) -> None:
    made = Harness(theatre(tmp_path))
    run = made.perform(request(script(INIT, OK), direction="fix the tests")).run
    performance = run.performance_id
    [(topic, started), (_, ended)] = performance_events(made, performance)
    assert topic == STARTED
    [run_started, *_] = run_lines(made, run.run_id)
    assert started["batch"]["id"] == run_started["batch"]["id"]
    state = started["state"]
    assert state["performed"] == {"kind": "actor", "name": "tester"}
    assert state["steps"] == [{"actor": "tester"}]
    assert state["direction"] == run_started["state"]["direction"]
    assert state["config"] == run_started["state"]["config"]
    assert run_started["state"]["step"] == 1
    assert run.step == 1
    assert ended["state"]["outcome"] == "completed"


def test_every_event_of_a_performance_and_its_run_names_the_performance(tmp_path: Path) -> None:
    made = Harness(theatre(tmp_path))
    run = made.perform(request(script(INIT, OK))).run
    lines = [line for _, line in performance_events(made, run.performance_id)]
    lines += run_lines(made, run.run_id)
    assert len(lines) >= 5
    assert {line["state"]["lineage"]["performance"] for line in lines} == {run.performance_id}


def test_a_worktree_steps_approvers_are_in_the_performances_start(repo: Repo) -> None:
    made = Harness(repo)
    run = gated(made, write("src/a.txt", "two\n"), OK)
    [(_, started), *_] = performance_events(made, run.performance_id)
    assert started["state"]["steps"] == [
        {"actor": "tester", "approvers": {"value": ["troupe", "director"], "source": "default"}}
    ]


def _requiring_a_missing_event(store: EventStore) -> EventStore:
    """A store whose batch holding a performance's start names an event that isn't here as one it
    requires, as a config version dropped meanwhile would (abandoned-edits design D4)."""
    original = store.record_with_lineages

    def record(events: Any, lineages: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if any(type(event).__qualname__ == "Performance.Started" for event in events):
            kwargs["requires"] = [*kwargs.get("requires", ()), "sha256:" + "f" * 64]
        return original(events, lineages, **kwargs)

    store.record_with_lineages = record  # type: ignore[method-assign]
    return store


def test_a_start_that_cant_be_recorded_records_neither_the_performance_nor_the_run(
    tmp_path: Path,
) -> None:
    made = Harness(theatre(tmp_path), store_wrapper=_requiring_a_missing_event)
    with pytest.raises(TroupeError) as caught:
        made.perform(request(script(INIT, OK)))
    assert caught.value.code == "events.required-missing"
    topics = {line["topic"] for line in recorded_lines(made.repo.path)}
    assert not any(topic.startswith(("troupe.core.runs.",)) for topic in topics)


def test_a_rehearsed_perform_records_no_performance(tmp_path: Path) -> None:
    made = Harness(theatre(tmp_path))
    made.perform_result({**request(script(INIT, OK)), "rehearse": True})
    topics = {line["topic"] for line in recorded_lines(made.repo.path)}
    assert not any(topic.startswith("troupe.core.runs.") for topic in topics)


# Requirement: A performance ends once nothing more will happen in it


def _ends_with_the_runs_end(made: Harness, run: m.RunSummary, outcome: str) -> None:
    [*_, (topic, ended)] = performance_events(made, run.performance_id)
    assert topic == ENDED
    assert ended["state"]["outcome"] == outcome
    run_end = run_lines(made, run.run_id)[-1]
    assert run_end["topic"].endswith("Run.Ended")
    assert ended["batch"]["id"] == run_end["batch"]["id"]
    assert ended["state"]["lineage"]["actor"]["kind"] == "human"
    assert ended["state"]["lineage"]["approvals"] == []


def test_a_run_that_succeeds_without_changes_completes_its_performance_with_its_end(
    tmp_path: Path,
) -> None:
    made = Harness(theatre(tmp_path))
    run = made.perform(request(script(INIT, OK))).run
    _ends_with_the_runs_end(made, run, "completed")


def test_a_failed_run_fails_its_performance_with_its_end(tmp_path: Path) -> None:
    made = Harness(theatre(tmp_path))
    run = made.perform(request(script(INIT, FAIL))).run
    assert run.outcome == "failed"
    _ends_with_the_runs_end(made, run, "failed")


def test_a_cancelled_run_cancels_its_performance_with_its_end(tmp_path: Path) -> None:
    made = Harness(theatre(tmp_path))
    made.cancel.request()
    run = made.perform(request(script(INIT, {"hang": True}))).run
    assert run.outcome == "cancelled"
    _ends_with_the_runs_end(made, run, "cancelled")


def test_a_run_that_couldnt_start_fails_its_performance_with_its_end(tmp_path: Path) -> None:
    made = Harness(theatre(tmp_path), limits=RunLimits(start_timeout=0.001))
    run = made.perform(request(script(INIT, OK))).run
    assert run.outcome == "could-not-start"
    _ends_with_the_runs_end(made, run, "failed")


def test_work_troupe_keeps_completes_the_performance_with_the_acceptance(repo: Repo) -> None:
    made = Harness(repo)
    run = gated(made, write("src/a.txt", "two\n"), OK)
    [*_, (topic, ended)] = performance_events(made, run.performance_id)
    assert topic == ENDED
    assert ended["state"]["outcome"] == "completed"
    accepted = run_lines(made, run.run_id)[-1]
    assert accepted["topic"].endswith("Run.ChangesAccepted")
    assert ended["batch"]["id"] == accepted["batch"]["id"]
    assert accepted["state"]["lineage"]["approvals"][0]["role"] == "troupe"
    assert ended["state"]["lineage"]["approvals"] == []
    assert ended["state"]["lineage"]["performance"] == run.performance_id


def test_work_waiting_for_a_person_leaves_the_performance_without_an_end(repo: Repo) -> None:
    made = Harness(repo)
    run = gated(made, write("src/a.txt", "two\n"), OK, approvers=["director"])
    assert [topic for topic, _ in performance_events(made, run.performance_id)] == [STARTED]


def test_work_troupe_passes_to_a_person_leaves_the_performance_without_an_end(repo: Repo) -> None:
    made = Recording(repo)
    made.on_running = lambda: (repo.path / "src" / "a.txt").write_bytes(b"mine\n")
    run = gated(made, write("src/a.txt", "two\n"), OK)
    assert (run.changes.state if run.changes else None) == "waiting"
    assert [topic for topic, _ in performance_events(made, run.performance_id)] == [STARTED]


# Requirement: Answering a gate ends a waiting performance


def test_approving_through_the_performance_completes_it_with_the_acceptance(repo: Repo) -> None:
    made = Harness(repo)
    run = gated(made, write("src/a.txt", "two\n"), OK, approvers=["director"])
    request_ = m.ApproveRequest.from_data({"run": run.performance_id, "reason": "fine"})
    result = call(made, gate.approve, request_)
    assert isinstance(result, m.AcceptResult)
    assert result.run == run.run_id
    [_, (topic, ended)] = performance_events(made, run.performance_id)
    assert topic == ENDED
    assert ended["state"]["outcome"] == "completed"
    accepted = run_lines(made, run.run_id)[-1]
    assert accepted["topic"].endswith("Run.ChangesAccepted")
    assert ended["batch"]["id"] == accepted["batch"]["id"]
    assert accepted["state"]["lineage"]["approvals"][0]["role"] == "director"
    assert ended["state"]["lineage"]["approvals"] == []
    for line in (accepted, ended):
        assert line["state"]["lineage"]["performance"] == run.performance_id
        assert line["state"]["lineage"]["actor"]["id"] == "ada@example.com"


def test_rejecting_ends_the_performance_rejected_with_the_rejection(repo: Repo) -> None:
    made = Harness(repo)
    run = gated(made, write("src/a.txt", "two\n"), OK, approvers=["director"])
    call(made, gate.reject, m.RejectRequest.from_data({"run": run.run_id, "reason": "no"}))
    [_, (topic, ended)] = performance_events(made, run.performance_id)
    assert topic == ENDED
    assert ended["state"]["outcome"] == "rejected"
    rejected = run_lines(made, run.run_id)[-1]
    assert rejected["topic"].endswith("Run.ChangesRejected")
    assert ended["batch"]["id"] == rejected["batch"]["id"]
    assert rejected["state"]["lineage"]["performance"] == run.performance_id


@pytest.mark.parametrize("settle", ["accept", "discard"])
def test_settling_a_failed_runs_changes_names_its_performance_and_records_nothing_in_it(
    repo: Repo, settle: str
) -> None:
    made = Harness(repo)
    run = gated(made, write("src/a.txt", "two\n"), FAIL)
    before = performance_events(made, run.performance_id)
    assert before[-1][1]["state"]["outcome"] == "failed"
    if settle == "accept":
        call(made, accept, m.AcceptRequest(run=run.run_id))
    else:
        call(made, discard, m.DiscardRequest(run=run.run_id))
    assert performance_events(made, run.performance_id) == before
    settled = run_lines(made, run.run_id)[-1]
    assert settled["topic"].endswith("Run.ChangesAccepted" if settle == "accept" else "Discarded")
    assert settled["state"]["lineage"]["performance"] == run.performance_id


# Requirement: Status reads runs from a projection (the limit counts performances)


def test_status_with_a_limit_of_two_lists_the_two_most_recent_performances(
    tmp_path: Path,
) -> None:
    made = Harness(theatre(tmp_path))
    runs = [made.perform(request(script(INIT, OK))).run for _ in range(3)]
    listed = made.status(limit=2).runs
    assert [(run.performance_id, run.run_id) for run in listed] == [
        (run.performance_id, run.run_id) for run in reversed(runs[1:])
    ]


# Requirement: Settling a run ends a performance its perform left open


def _left_open(repo: Repo, monkeypatch: pytest.MonkeyPatch) -> tuple[Harness, m.RunSummary]:
    """A run whose perform stopped after its end and before troupe's turn at its gate: its
    changes are pending, and its performance has no end."""
    monkeypatch.setattr(gate, "troupes_step", lambda *_, **__: None)
    made = Harness(repo)
    run = gated(made, write("src/a.txt", "two\n"), OK)
    assert (run.changes.state if run.changes else None) == "pending"
    assert [topic for topic, _ in performance_events(made, run.performance_id)] == [STARTED]
    return made, run


@pytest.mark.parametrize(("settle", "outcome"), [("accept", "completed"), ("discard", "rejected")])
def test_settling_a_run_whose_performance_was_left_open_ends_it_in_the_same_batch(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, settle: str, outcome: str
) -> None:
    made, run = _left_open(repo, monkeypatch)
    if settle == "accept":
        call(made, accept, m.AcceptRequest(run=run.performance_id))
    else:
        call(made, discard, m.DiscardRequest(run=run.performance_id))
    [_, (topic, ended)] = performance_events(made, run.performance_id)
    assert topic == ENDED
    assert ended["state"]["outcome"] == outcome
    settled = run_lines(made, run.run_id)[-1]
    assert ended["batch"]["id"] == settled["batch"]["id"]
    assert settled["state"]["lineage"]["approvals"] == []
    assert ended["state"]["lineage"]["approvals"] == []
    assert ended["state"]["lineage"]["performance"] == run.performance_id


# Requirement: A run recorded before performances is refused with its fix (perform refuses first)


def _record_an_old_run(made: Harness) -> str:
    """A run's start as a troupe before performances recorded it, with no performance in its
    lineage. The service refuses to record that now, so it goes to the recorder directly."""
    from protocol_guard import unchecked
    from troupe.core.runs.aggregate import Run

    run_id = "01d00000-0000-4000-8000-000000000000"
    run = Run(
        run_id=run_id,
        actor="tester",
        runner_requested="scripted",
        stage={
            "name": "local",
            "effects": "unenforced",
            "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
        },
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=["sha256:" + "b" * 64],
        workspace={"kind": "theatre"},
        on_context_full={"value": "fail", "source": "default"},
        step=1,
    )
    store = made.backends().event_store(made.session())
    lineage = store.command(via="cli").lineage().to_data()
    with unchecked():  # invalid on purpose: an older troupe's record
        stored = [store._stored(event, lineage) for event in run.collect_events()]
    store.recorder.insert(stored)
    return run_id


@pytest.mark.parametrize("rehearse", [False, True], ids=["for real", "rehearsed"])
def test_perform_refuses_a_theatre_holding_a_run_from_before_performances_before_running(
    repo: Repo, rehearse: bool
) -> None:
    made = Harness(repo)
    old = _record_an_old_run(made)
    asked = configured(made, INIT, write("src/a.txt", "two\n"), OK, effects=EVERYWHERE)
    before = {line["id"] for line in recorded_lines(repo.path)}
    with pytest.raises(TroupeError) as caught:
        made.perform_result({**asked, **({"rehearse": True} if rehearse else {})})
    assert caught.value.code == "run.recorded-before-performances"
    assert caught.value.details["runs"] == [old]
    after = [line for line in recorded_lines(repo.path) if line["id"] not in before]
    assert not [line for line in after if line["topic"].startswith("troupe.core.runs.")]
    assert not [u for u in made.updates if u.get("kind") in ("started", "event")]
