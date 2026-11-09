"""status and logs read runs back from projections (spec: runs; perform-status-logs design D11 to
D13)."""

import json
import math
import os
import queue
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from gitrepo import Repo, clone
from runtesting import INIT, OK, Harness, failing_at, request, script, theatre, turn
from storetesting import (
    FOLLOW_BOUND,
    SLOW_STRETCH_SECONDS,
    STALL_SECONDS,
    WITHIN,
    git_service,
    settle,
    wait_until,
    watched_delays,
)
from troupe.core import defaults
from troupe.core.client import messages as m
from troupe.core.errors import TroupeError
from troupe.core.events import EventStore
from troupe.core.notices import Notice
from troupe.core.runs.aggregate import Run
from troupe.platform.errors import WatchUnavailableError
from troupe.platform.watching import DirectoryWatch
from troupe_plugin_sdk import runner as p

CHILD = Path(__file__).with_name("perform_child.py")
HANG = script(INIT, turn("one"), {"hang": True})
STAGE = {
    "name": "local",
    "effects": "unenforced",
    "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
}


class Child:
    """perform running in another process."""

    def __init__(
        self,
        repo: Repo,
        options: dict[str, Any],
        *,
        appends: Path | None = None,
        shown: Path | None = None,
        stop: str | None = None,
        silence: float | None = None,
        **fields: Any,  # noqa: ANN401
    ) -> None:
        """``appends``: a file outside the theatre where the child notes when each segment
        append returned, and the run events it wrote. ``shown``: a file outside the theatre
        where the test lists each seq its follower has shown, and the child waits for each before
        recording the next (windows-follow-flake design D5). ``stop``: where the child announces the
        run instead of at its first event, and ``fields``: more of the request, such as its
        workspace (perform_child.py). ``silence``: the seconds after which its run announces a
        silence."""
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(CHILD),
                str(repo.path),
                json.dumps(repo.env),
                json.dumps(request(options, **fields)),
                *([str(appends)] if appends is not None else []),
            ],
            stdout=subprocess.PIPE,
            text=True,
            env={
                **os.environ,
                **({"TROUPE_TEST_STOP": stop} if stop is not None else {}),
                **({"TROUPE_TEST_SHOWN": str(shown)} if shown is not None else {}),
                **({"TROUPE_TEST_SILENCE_SECONDS": str(silence)} if silence is not None else {}),
            },
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


def events_of(result: m.LogsResult) -> list[m.LoggedEvent]:
    """The run events in a logs result's log, without its recorded notices."""
    return [entry for entry in result.log if isinstance(entry, m.LoggedEvent)]


def recorded_start(store: EventStore, run_id: str) -> None:
    """A run's start and first event, recorded as perform records them, with no end."""
    run = Run(
        run_id=run_id,
        actor="tester",
        runner_requested="scripted",
        stage=STAGE,
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=["sha256:" + "b" * 64],
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
    notice = Notice(
        "events.order-rebuilt", problem="Rebuilt.", fix="Nothing to do.", details={"gone": 2}
    )

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


# Reading back what perform records before the runner starts (account-for-every-worktree design D3,
# D4, D7).

WORKTREE = {
    "kind": "worktree",
    "path": ".troupe/local/worktrees/6f1d2c3b-0000-4000-8000-000000000002",
    "base": "c" * 40,
    "dirty": False,
}


def started(
    store: EventStore, workspace: dict[str, Any], runner_reported: dict[str, Any] | None = None
) -> Run:
    """A run's start as perform records it, or, with ``runner_reported``, as an older troupe
    did."""
    run = Run(
        run_id="6f1d2c3b-0000-4000-8000-000000000002",
        actor="tester",
        runner_requested="scripted",
        stage=STAGE,
        effect_check={"kind": "none"},
        direction="sha256:" + "a" * 64,
        config=["sha256:" + "b" * 64],
        workspace=workspace,
        runner_reported=runner_reported,
    )
    store.command(via="cli").record(run.collect_events())
    return run


def init(run: Run) -> dict[str, Any]:
    return {**INIT["event"], "runId": run.run_id, "seq": 0}


def test_a_runs_reported_runner_is_read_from_its_init_event(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    store = git_service(harness.repo)
    run = started(store, {"kind": "theatre"})
    run.report(0, init(run))
    store.command(via="runner").record(run.collect_events())
    [summary] = harness.status(run=run.run_id).runs
    assert summary.to_data()["runner"] == {
        "requested": "scripted",
        "reported": {"name": "scripted", "version": "0.1.0"},
    }


def test_a_run_ended_before_its_runner_sent_init_has_no_reported_runner(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    store = git_service(harness.repo)
    run = started(store, {"kind": "theatre"})
    run.report(0, {"runId": run.run_id, "seq": 0, "type": "log", "level": "info", "message": "m"})
    store.command(via="runner").record(run.collect_events())
    [summary] = harness.status(run=run.run_id).runs
    assert summary.to_data()["runner"] == {"requested": "scripted"}


def test_a_worktree_not_made_yet_has_no_clones_and_one_made_has_them(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    store = git_service(harness.repo)
    run = started(store, WORKTREE)
    [summary] = harness.status(run=run.run_id).runs
    assert summary.to_data()["workspace"] == WORKTREE
    run.made_worktree(["copy"])
    store.command(via="cli").record(run.collect_events())
    [summary] = harness.status(run=run.run_id).runs
    assert summary.to_data()["workspace"] == {**WORKTREE, "clones": ["copy"]}


def test_a_start_an_older_troupe_recorded_reads_back_its_runner_and_clones(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    store = git_service(harness.repo)
    reported = {"name": "scripted", "version": "0.0.9"}
    run = started(store, {**WORKTREE, "clones": ["symlink"]}, runner_reported=reported)
    [summary] = harness.status(run=run.run_id).runs
    data = summary.to_data()
    assert data["runner"]["reported"] == reported
    assert data["workspace"]["clones"] == ["symlink"]


# 8.3: logs.


def test_logs_return_a_runs_events_in_seq_order_with_their_recording_times(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    run_id = harness.perform(request(script(INIT, turn("a"), turn("b"), OK))).run.run_id
    result = harness.logs(run=run_id)
    assert [(e.seq, e.event.TYPE) for e in events_of(result)] == [
        (0, "init"),
        (1, "turn"),
        (2, "turn"),
        (3, "result"),
    ]
    recorded = harness.stores[-1].history(UUID(run_id))[1:5]
    assert [e.at for e in events_of(result)] == [(r.lineage or {}).get("at") for r in recorded]
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
    assert [e.seq for e in events_of(result)] == [0, 1, 2, 3]
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


QUIET = {"poll_seconds": 60, "check_seconds": 60}
"""Store settings under which only a notification can wake a follower within a test's bounds."""


def refusing(directory: Path) -> DirectoryWatch:
    raise WatchUnavailableError(directory, "the platform refused (a test)")


def follow_in_background(harness: Harness, run_id: str) -> tuple[threading.Thread, list[Any]]:
    result: list[Any] = []

    def following() -> None:
        result.append(harness.logs(run=run_id, follow=True))

    thread = threading.Thread(target=following, daemon=True)
    thread.start()
    return thread, result


def test_following_shows_another_processs_events_each_before_the_next_the_fastest_under_the_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child records each event only once following has shown the one before (windows-follow-
    flake design D1). With the store's poll and check (QUIET) and following's lease check all at
    60 s, only the store's subscription can wake following inside the test (D4), and the next
    event isn't written yet: so each event shown was shown on its own write's wake, however
    loaded the machine. Speed is sampled like the store's watched deliveries (D2): five, then
    more while none is under FOLLOW_BOUND, until a slow stretch's budget runs out."""
    monkeypatch.setattr(defaults, "LOGS_LEASE_CHECK_SECONDS", 60)
    repo = theatre(tmp_path / "theatre")
    appends, shown = tmp_path / "appends.txt", tmp_path / "shown.txt"
    # Each measurement after the fifth took at least FOLLOW_BOUND, or sampling would have stopped.
    turns = 5 + math.ceil(SLOW_STRETCH_SECONDS / FOLLOW_BOUND) + 1
    steps = [INIT, *(turn(str(n)) for n in range(turns)), OK]
    child = Child(repo, script(*steps), appends=appends, shown=shown)
    arrivals: queue.Queue[tuple[int, float]] = queue.Queue()
    followed: list[int] = []

    class Timing(Harness):
        def send(self, update: Any) -> None:  # noqa: ANN401
            data = update.to_data()
            if data["kind"] == "event":
                followed.append(data["seq"])
                arrivals.put((data["seq"], time.time()))

    def show(line: str) -> None:
        with shown.open("a", encoding="utf-8") as out:
            out.write(f"{line}\n")

    received: dict[int, float] = {}

    def receive(seq: int) -> None:
        """Wait for following to show ``seq``, the next event, and tell the child it has."""
        try:
            got, at = arrivals.get(timeout=WITHIN)
        except queue.Empty:
            pytest.fail(f"following didn't show seq {seq} within {WITHIN} s; shown: {followed}")
        assert got == seq, followed
        received[seq] = at
        show(str(seq))

    def appended_at(seq: int) -> float:
        """When the child's append of ``seq`` returned. The child notes it just after the append,
        so following may have shown the event first."""
        noted: dict[int, float] = {}

        def find() -> bool:
            text = appends.read_text(encoding="utf-8") if appends.exists() else ""
            for line in text[: text.rfind("\n") + 1].splitlines():
                at, *seqs = line.split()
                noted.update((int(each), float(at)) for each in seqs)
            return seq in noted

        wait_until(find, f"the child noting when its append of seq {seq} returned")
        return noted[seq]

    appended: dict[int, float] = {}

    def measure() -> float:
        seq = len(received)
        receive(seq)
        appended[seq] = appended_at(seq)
        return received[seq] - appended[seq]

    harness = Timing(repo, store_options=QUIET)
    try:
        thread, result = follow_in_background(harness, child.run_id)
        receive(0)  # recorded before following began; seq 1 is written only after it's shown
        delays = watched_delays(measure, bound=FOLLOW_BOUND)
    except BaseException:
        harness.cancel.request()
        child.kill()
        raise
    finally:
        show("stop")
    out = child.finish()
    thread.join(timeout=WITHIN)
    assert not thread.is_alive(), "following didn't stop once the run ended"
    assert "ENDED succeeded" in out, out
    assert "UNSHOWN" not in out, out
    assert followed == list(range(turns + 2)), followed
    assert result[0].run.state == "ended"
    # Each event reached following before the child recorded the next: the handshake's order.
    for seq in appended:
        assert received[seq - 1] < appended[seq], (seq, received, appended)
    assert min(delays) < FOLLOW_BOUND, delays
    assert statistics.median(delays[:5]) < FOLLOW_BOUND + STALL_SECONDS, delays


def test_following_a_quiet_run_reads_no_segment_while_it_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = theatre(tmp_path)
    child = Child(repo, HANG)
    looks: list[float] = []

    def counting(store: EventStore) -> EventStore:
        sizes = store.recorder._sizes  # type: ignore[attr-defined]

        def counted() -> dict[str, int]:
            looks.append(time.monotonic())
            return sizes()  # type: ignore[no-any-return]

        monkeypatch.setattr(store.recorder, "_sizes", counted)
        return store

    try:
        harness = Harness(repo, store_options=QUIET, store_wrapper=counting)
        thread, _ = follow_in_background(harness, child.run_id)
        # The child has recorded all it will (HANG's turn is seq 1), and following has read it.
        wait_until(
            lambda: any(u["kind"] == "event" and u["seq"] == 1 for u in harness.updates),
            "following sending the turn HANG records before it hangs (seq 1)",
        )
        settle(looks)
        looks.clear()
        time.sleep(2.0)
        assert looks == []
        harness.cancel.request()
        thread.join(timeout=10)
    finally:
        child.kill()


def test_following_an_unwatchable_store_sends_its_polling_notice_first_and_still_delivers(
    tmp_path: Path,
) -> None:
    repo = theatre(tmp_path)
    child = Child(repo, script(INIT, {"wait": {"ms": 500}}, turn("a"), OK))
    harness = Harness(repo, store_options={"poll_seconds": 0.2, "watcher": refusing})
    result = harness.logs(run=child.run_id, follow=True)
    assert "ENDED succeeded" in child.finish()
    first = harness.updates[0]
    assert first["kind"] == "notice"
    assert first["notice"]["code"] == "events.subscription-polling"
    assert first["notice"]["details"]["reason"] == "watch-refused"
    followed = [u["seq"] for u in harness.updates if u["kind"] == "event"]
    assert followed == [0, 1, 2]
    assert [n.code for n in result.notices].count("events.subscription-polling") == 1
    assert result.run.state == "ended"


def test_killing_perform_while_its_run_is_followed_stops_following_within_the_lease_check(
    tmp_path: Path,
) -> None:
    repo = theatre(tmp_path)
    child = Child(repo, HANG)
    harness = Harness(repo, store_options=QUIET)
    thread, result = follow_in_background(harness, child.run_id)
    time.sleep(1.0)
    killed = time.monotonic()
    child.kill()
    thread.join(timeout=30)
    assert result, "following didn't stop"
    assert time.monotonic() - killed < defaults.LOGS_LEASE_CHECK_SECONDS + 3
    assert result[0].run.state == "interrupted"
    assert [n.code for n in result[0].notices] == ["run.interrupted"]


# Requirement: Init says how the runner applies the effects (declared-effects): a run recorded
# before runners said still reads.


def test_a_run_whose_init_was_recorded_without_effects_still_shows_in_status_and_logs(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    store = git_service(harness.repo)
    run = started(store, {"kind": "theatre"})
    legacy = {key: value for key, value in init(run).items() if key != "effects"}
    assert "effects" not in legacy
    run.report(0, legacy)
    store.command(via="runner").record(run.collect_events())
    [summary] = harness.status(run=run.run_id).runs
    assert summary.to_data()["runner"]["reported"] == {"name": "scripted", "version": "0.1.0"}
    [logged] = [e for e in events_of(harness.logs(run=run.run_id)) if e.seq == 0]
    assert isinstance(logged.event, p.InitEvent)
    assert logged.event.effects is None
