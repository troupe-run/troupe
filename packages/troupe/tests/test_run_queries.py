"""status and logs read runs back from projections (spec: runs; perform-status-logs design D11 to
D13)."""

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from gitrepo import Repo, clone
from runtesting import INIT, OK, Harness, failing_at, request, script, theatre, turn
from storetesting import git_service
from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.notices import Notice
from troupe.core.runs.aggregate import Run

CHILD = Path(__file__).with_name("perform_child.py")
HANG = script(INIT, turn("one"), {"hang": True})
STAGE = {
    "name": "local",
    "effects": "unenforced",
    "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
}


class Child:
    """perform running in another process."""

    def __init__(self, repo: Repo, options: dict[str, Any]) -> None:
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(CHILD),
                str(repo.path),
                json.dumps(repo.env),
                json.dumps(request(options)),
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert self.process.stdout is not None
        line = self.process.stdout.readline().split()
        assert line[:1] == ["STARTED"], line
        self.run_id = line[1]

    def kill(self) -> None:
        self.process.kill()
        self.process.wait(timeout=30)

    def finish(self) -> str:
        assert self.process.stdout is not None
        out, _ = self.process.communicate(timeout=60)
        return out


def recorded_start(store: EventStore, run_id: str) -> None:
    """A run's start and first event, recorded as perform records them, with no end."""
    run = Run(
        run_id=run_id,
        actor="tester",
        runner_requested="scripted",
        runner_reported={"name": "scripted", "version": "0.1.0"},
        stage=STAGE,
        effect_check={"kind": "none"},
        instructions="sha256:" + "a" * 64,
        options="sha256:" + "b" * 64,
    )
    store.command(via="cli").record(run.collect_events())
    run.report(0, {"runId": run_id, "seq": 0, "type": "log", "level": "info", "message": "m"})
    store.command(via="runner").record(run.collect_events())


# 8.1: each derived state.


def test_a_run_whose_end_is_recorded_is_ended(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    run_id = harness.perform(request(script(INIT, OK))).run.run_id
    [run] = harness.status(run=run_id).runs
    assert (run.state, run.outcome) == ("ended", "succeeded")


def test_a_run_whose_perform_is_alive_in_another_process_is_running(tmp_path: Path) -> None:
    repo = theatre(tmp_path)
    child = Child(repo, HANG)
    try:
        result = Harness(repo).status(run=child.run_id)
        [run] = result.runs
        assert run.state == "running"
        assert run.outcome is None
        assert run.events >= 1
        assert result.notices == []
    finally:
        child.kill()


def test_a_run_whose_perform_was_killed_is_interrupted_and_nothing_is_recorded_for_it(
    tmp_path: Path,
) -> None:
    repo = theatre(tmp_path)
    child = Child(repo, HANG)
    child.kill()
    harness = Harness(repo)
    result = harness.status(run=child.run_id)
    [run] = result.runs
    assert run.state == "interrupted"
    assert run.ended_at is None
    assert [n.code for n in result.notices] == ["run.interrupted"]
    topics = [r.topic for r in harness.stores[0].history(UUID(child.run_id))]
    assert not any(t.endswith("Run.Ended") for t in topics)


def test_a_run_that_arrived_by_merge_from_another_clone_is_unfinished_elsewhere(
    tmp_path: Path,
) -> None:
    here = theatre(tmp_path)
    (here.path / ".troupe" / "keep").write_text("", encoding="utf-8")
    here.commit_all("theatre")
    there = clone(here, tmp_path, "there")
    run_id = "6f1d2c3b-0000-4000-8000-000000000001"
    recorded_start(git_service(there), run_id)
    there.commit_all("a run started there")
    here.git("pull", "-q", str(there.path), "main")
    result = Harness(here).status(run=run_id)
    [run] = result.runs
    assert run.state == "unfinished-elsewhere"
    assert [n.code for n in result.notices] == ["run.unfinished-elsewhere"]


def test_a_run_whose_end_could_not_be_recorded_shows_as_interrupted(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path), store_wrapper=failing_at(1, end_too=True))
    with pytest.raises(TroupeError) as caught:
        harness.perform(request(script(INIT, turn("one"), {"hang": True})))
    run_id = caught.value.details["run"]
    [run] = Harness(harness.repo).status(run=run_id).runs
    assert run.state == "interrupted"


# 8.2: status.


def performed(harness: Harness, count: int) -> list[str]:
    return [harness.perform(request(script(INIT, OK))).run.run_id for _ in range(count)]


def test_status_lists_runs_newest_first(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    ids = performed(harness, 3)
    assert [r.run_id for r in harness.status().runs] == list(reversed(ids))


def test_status_lists_at_most_the_default_limit_or_the_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness(theatre(tmp_path))
    ids = performed(harness, 3)
    monkeypatch.setattr(defaults, "STATUS_RUNS_LIMIT", 2)
    assert [r.run_id for r in harness.status().runs] == [ids[2], ids[1]]
    assert [r.run_id for r in harness.status(limit=1).runs] == [ids[2]]
    assert len(harness.status(limit=3).runs) == 3


def test_a_run_is_found_by_its_full_id_or_a_unique_prefix(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    [run_id] = performed(harness, 1)
    assert [r.run_id for r in harness.status(run=run_id).runs] == [run_id]
    assert [r.run_id for r in harness.status(run=run_id[:8]).runs] == [run_id]


def test_a_prefix_that_matches_no_run_is_refused(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    performed(harness, 1)
    with pytest.raises(TroupeError) as caught:
        harness.status(run="00000000")
    assert caught.value.code == "run.not-found"


def test_a_prefix_two_runs_share_is_refused_listing_both(tmp_path: Path) -> None:
    repo = theatre(tmp_path)
    store = git_service(repo)
    first = "1a2b3c4d-0000-4000-8000-000000000001"
    second = "1a2b3c4d-0000-4000-8000-000000000002"
    recorded_start(store, first)
    recorded_start(store, second)
    with pytest.raises(TroupeError) as caught:
        Harness(repo).status(run="1a2b3c4d")
    assert caught.value.code == "run.ambiguous-id"
    assert caught.value.details["matches"] == [first, second]


def test_the_stores_notices_come_back_with_the_result(tmp_path: Path) -> None:
    notice = Notice("events.order-rebuilt", problem="Rebuilt.", fix="Nothing to do.")

    def with_notice(store: EventStore) -> EventStore:
        store.notices = lambda: [notice]  # type: ignore[method-assign]
        return store

    harness = Harness(theatre(tmp_path), store_wrapper=with_notice)
    assert [n.code for n in harness.status().notices] == ["events.order-rebuilt"]


def test_a_summary_says_who_started_the_run_and_on_what_stage(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    [run_id] = performed(harness, 1)
    [run] = harness.status(run=run_id).runs
    data = run.to_data()
    assert data["startedBy"] == {"kind": "human", "id": "ada@example.com", "source": "env"}
    assert data["stage"] == STAGE
    assert data["actor"] == "tester"
    assert data["runner"]["requested"] == "scripted"


# 8.3: logs.


def test_logs_return_a_runs_events_in_seq_order_with_their_recording_times(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    run_id = harness.perform(request(script(INIT, turn("a"), turn("b"), OK))).run.run_id
    result = harness.logs(run=run_id)
    assert [(e.seq, e.event.TYPE) for e in result.events] == [
        (0, "init"),
        (1, "turn"),
        (2, "turn"),
        (3, "result"),
    ]
    recorded = harness.stores[-1].history(UUID(run_id))[1:5]
    assert [e.at for e in result.events] == [(r.lineage or {}).get("at") for r in recorded]
    assert result.run.state == "ended"


def test_following_from_another_process_sees_each_event_and_stops_at_the_end(
    tmp_path: Path,
) -> None:
    repo = theatre(tmp_path)
    slow = script(INIT, {"wait": {"ms": 1500}}, turn("a"), {"wait": {"ms": 1500}}, turn("b"), OK)
    child = Child(repo, slow)
    harness = Harness(repo)
    started = time.monotonic()
    result = harness.logs(run=child.run_id, follow=True)
    assert "ENDED succeeded" in child.finish()
    followed = [(u["seq"], u["event"]["type"]) for u in harness.updates if u["kind"] == "event"]
    assert followed == [(0, "init"), (1, "turn"), (2, "turn"), (3, "result")]
    assert [e.seq for e in result.events] == [0, 1, 2, 3]
    assert result.run.state == "ended"
    assert time.monotonic() - started >= 2.0  # it waited for events still to come


def test_following_an_interrupted_run_returns_at_once_saying_why(tmp_path: Path) -> None:
    repo = theatre(tmp_path)
    child = Child(repo, HANG)
    child.kill()
    harness = Harness(repo)
    started = time.monotonic()
    result = harness.logs(run=child.run_id, follow=True)
    assert time.monotonic() - started < defaults.SUBSCRIBE_POLL_SECONDS + 5
    assert result.run.state == "interrupted"
    assert [n.code for n in result.notices] == ["run.interrupted"]


def test_following_stops_when_cancelled(tmp_path: Path) -> None:
    repo = theatre(tmp_path)
    child = Child(repo, HANG)
    try:
        harness = Harness(repo)
        threading.Timer(1.0, harness.cancel.request).start()
        result = harness.logs(run=child.run_id, follow=True)
        assert result.run.state == "running"
    finally:
        child.kill()


def test_following_shows_each_event_within_a_few_tenths_of_a_second_of_its_recording(
    tmp_path: Path,
) -> None:
    repo = theatre(tmp_path)
    gaps = [{"wait": {"ms": 700}}, turn("a"), {"wait": {"ms": 700}}, turn("b")]
    child = Child(repo, script(INIT, *gaps, {"wait": {"ms": 700}}, OK))
    received: dict[int, float] = {}

    class Timing(Harness):
        def send(self, update: Any) -> None:  # noqa: ANN401
            data = update.to_data()
            if data["kind"] == "event":
                received[data["seq"]] = time.time()

    Timing(repo).logs(run=child.run_id, follow=True)
    child.finish()
    history = git_service(repo).history(UUID(child.run_id))
    recorded = {
        json.loads(r.state)["seq"]: datetime.fromisoformat(r.lineage["at"]).timestamp()
        for r in history
        if r.topic.endswith("Run.Reported") and r.lineage is not None
    }
    # seq 0 was recorded before following began; every later one arrived while following.
    lags = sorted(received[seq] - recorded[seq] for seq in recorded if seq > 0)
    assert len(lags) == 3
    assert lags[len(lags) // 2] < 0.4, lags
