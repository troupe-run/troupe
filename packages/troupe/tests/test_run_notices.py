"""A run's notices are kept in its history (spec: runs, client-protocol; run-notices-in-history
design D2 to D8).

Each test performs real runs with the scripted runner, then reads the run's stream back: which
notices it recorded, where among its events, with whose lineage, and what status and logs show.
"""

import asyncio
import contextlib
import importlib
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from client_schemas import check
from runtesting import INIT, OK, Harness, committed, request, script, theatre
from storetesting import files_service, git_service
from test_perform import configured
from test_run_aggregate import STAGE, outcome
from test_run_queries import Child
from troupe.core.client import messages as m
from troupe.core.errors import TroupeError
from troupe.core.identity import Identity
from troupe.core.masking import MARKER
from troupe.core.notices import Notice
from troupe.core.runners.limits import RunLimits
from troupe.core.runs.aggregate import (
    ENDED,
    NOTICED,
    REPORTED,
    STARTED,
    Run,
)
from troupe.core.runs.perform import lease_dir
from troupe.core.workspaces import Announce
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.messages import Message

# troupe.core.runs re-exports perform the function, so the modules are reached by name.
perform_module = importlib.import_module("troupe.core.runs.perform")
host_module = importlib.import_module("troupe.core.runners.host")
workspaces_module = importlib.import_module("troupe.core.workspaces")

QUICK_SILENCE = RunLimits(
    start_timeout=10.0, cancel_grace=2.0, run_timeout=20.0, silence_announce=0.3
)
"""Limits under which a 0.8 s wait is announced as a silence. So is a runner that takes longer than
0.3 s to send its init, or troupe taking longer than that to record an event, as either can on a
loaded CI machine: see apart_from_silences."""
WAIT = {"wait": {"ms": 800}}
RETRY = {
    "event": {
        "type": "retry",
        "attempt": 1,
        "maxAttempts": 10,
        "delayMs": 500,
        "reason": "rate-limit",
    }
}
ADA_ACTOR = {"kind": "human", "id": "ada@example.com", "source": "env"}
KEY = "sk-test/canary-0123456789abcdef"


def records(harness: Harness, run_id: str) -> list[Any]:
    return list(harness.stores[0].history(UUID(run_id)))


def shape(harness: Harness, run_id: str) -> list[str]:
    """The run's stream as topics, with each recorded notice's code and each event's type."""
    named: list[str] = []
    for record in records(harness, run_id):
        state = json.loads(record.state)
        if record.topic == NOTICED:
            named.append(f"notice {state['notice']['code']}")
        elif record.topic == REPORTED:
            named.append(f"event {state['event']['type']}")
        else:
            named.append(record.topic.rsplit(".", 1)[-1])
    return named


def apart_from_silences(named: list[str], after: str) -> list[str]:
    """``named`` (a shape, or a log's kinds and codes) without its run.silent notices, once checked
    that one comes straight after ``after``, before the next event: the silence a test's wait makes.

    Under QUICK_SILENCE that isn't the only silence a run can have. The silence clock runs from the
    last event's arrival, and troupe reads the runner's next line only once it has recorded that
    event, so a runner slow to send its init, or a slow write (fsync and git on a loaded Windows
    runner), counts as a silence too: a real one, rightly recorded wherever it falls. Every other
    entry keeps its exact place."""
    start = named.index(after)
    following = [
        i for i in range(start + 1, len(named)) if named[i].startswith(("event ", "Ended"))
    ]
    end = following[0] if following else len(named)
    assert "notice run.silent" in named[start + 1 : end], (after, named)
    return [name for name in named if name != "notice run.silent"]


def apart_from_waits(named: list[str]) -> list[str]:
    """``named`` (a shape) without its workspace.waiting notices. Looking for uncommitted changes,
    or making, filling, capturing or removing a run's worktree, is announced once it outlasts
    WORKSPACE_ANNOUNCE_AFTER_SECONDS, as it can on a loaded Windows runner (#380): a real notice,
    rightly recorded wherever it falls. Every other entry keeps its exact place."""
    return [name for name in named if name != "notice workspace.waiting"]


def live(harness: Harness, code: str) -> list[dict[str, Any]]:
    """The notices with ``code`` that perform sent live, as updates."""
    return [
        update["notice"]
        for update in harness.updates
        if update.get("kind") == "notice" and update["notice"]["code"] == code
    ]


def refusing_scratch(monkeypatch: pytest.MonkeyPatch, problem: str = "") -> None:
    """Make removing a run's scratch directory raise run.scratch-not-removed, after its runner
    ended, as a directory still in use would."""

    def refuse(scratch: Path) -> Notice:
        return Notice(
            "run.scratch-not-removed",
            problem=f"The run's scratch directory {scratch} couldn't be removed: busy.{problem}",
            fix=f"Remove {scratch} yourself once nothing is using it.",
            path=str(scratch),
            details={"scratch": str(scratch)},
        )

    monkeypatch.setattr(host_module, "remove_scratch", refuse)


# Requirement: A run's notices are recorded in its stream


def test_a_silence_and_a_retry_are_recorded_in_order_among_the_runs_events_and_sent_live(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path), limits=QUICK_SILENCE)
    run = harness.perform(request(script(INIT, WAIT, RETRY, OK))).run
    named = shape(harness, run.run_id)
    assert apart_from_silences(named, after="event init") == [
        "Started",
        "event init",
        "event retry",
        "notice run.retrying",
        "event result",
        "Ended",
    ]
    assert len(live(harness, "run.silent")) == named.count("notice run.silent")
    assert len(live(harness, "run.retrying")) == 1


@contextlib.contextmanager
def announced_at_once(what: str, announce: Announce, after: float) -> Iterator[None]:
    """workspaces.announced on a runner slow enough to announce every operation: workspace.waiting
    is raised as the operation starts, as a loaded Windows runner raised it after 2 s (#380)."""
    announce(
        Notice(
            "workspace.waiting",
            problem=f"troupe is still {what}, after {after:g}s.",
            fix="Nothing to do: a large repository takes longer.",
            details={"operation": what, "waitedSeconds": after},
        )
    )
    yield


@pytest.mark.parametrize("worktree", ["quick", "slow"])
def test_a_notice_raised_before_the_start_is_recorded_straight_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worktree: str
) -> None:
    if worktree == "slow":
        monkeypatch.setattr(workspaces_module, "announced", announced_at_once)
    repo = committed(tmp_path)
    harness = Harness(repo)
    asked = request(script(INIT, OK), workspace="worktree")
    harness.configure(asked)
    repo.commit_all("config")
    repo.write("src/a.txt", "edited, not committed\n")
    run = harness.perform(asked).run
    named = shape(harness, run.run_id)
    if worktree == "slow":
        assert "notice workspace.waiting" in named[: named.index("WorktreeMade")], named
    assert apart_from_waits(named)[:3] == [
        "Started",
        "notice workspace.uncommitted-unseen",
        "WorktreeMade",
    ], named
    assert len(live(harness, "workspace.uncommitted-unseen")) == 1


def test_a_notice_raised_after_the_runner_ends_is_recorded_before_the_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusing_scratch(monkeypatch)
    harness = Harness(theatre(tmp_path))
    run = harness.perform(request(script(INIT, OK))).run
    assert shape(harness, run.run_id)[-2:] == ["notice run.scratch-not-removed", "Ended"]
    assert run.outcome == "succeeded"


def test_a_recorded_notice_holds_the_notice_exactly_as_it_was_sent_live(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    run = harness.perform(request(script(INIT, RETRY, OK))).run
    [noticed] = [json.loads(r.state) for r in records(harness, run.run_id) if r.topic == NOTICED]
    assert noticed["notice"] == live(harness, "run.retrying")[0]


# Requirement: Who started a run and who acted in it are both recorded (a recorded notice)


def test_a_recorded_notice_is_the_persons_under_the_runs_change(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path), limits=QUICK_SILENCE)
    run = harness.perform(request(script(INIT, WAIT, OK))).run
    stream = records(harness, run.run_id)
    noticed = [r for r in stream if r.topic == NOTICED]
    assert noticed  # the wait's silence, and any while the runner started
    change = stream[0].lineage["change"]
    for record in noticed:
        assert record.lineage["actor"] == ADA_ACTOR
        assert record.lineage["via"] == "cli"
        assert record.lineage["change"] == change
        assert record.lineage["cause"] == {"kind": "command", "id": change}


# Requirement: Only a run's own notices are recorded in it


def test_a_config_file_rewritten_before_the_run_is_sent_but_not_recorded(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    asked = request(script(INIT, OK))
    configured(harness, asked)
    (harness.repo.path / ".troupe" / "actors" / "tester.yaml").unlink()
    run = harness.perform(asked).run
    assert len(live(harness, "config.file-rewritten")) == 1
    assert NOTICED not in [record.topic for record in records(harness, run.run_id)]


def test_reading_an_interrupted_run_returns_run_interrupted_and_records_nothing(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    run_id = interrupted_with_a_notice(harness)
    store = git_service(harness.repo)
    before = [record.topic for record in store.history(UUID(run_id))]
    status = harness.status(run=run_id)
    assert status.runs[0].state == "interrupted"
    assert [n.code for n in status.notices] == ["run.interrupted"]
    logged = harness.logs(run=run_id)
    assert [n.code for n in logged.notices] == ["run.interrupted"]
    assert [record.topic for record in store.history(UUID(run_id))] == before


# Requirement: A recording failure stops the run and is reported (a notice)


def failing_notice(code: str) -> Any:  # noqa: ANN401
    """A store wrapper whose write of the notice ``code`` fails as a full disk would."""

    def wrap(store: Any) -> Any:  # noqa: ANN401
        original = store.record_with_lineage

        def record(events: Any, lineage: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            for event in events:
                if type(event).__qualname__ == "Run.Noticed" and event.notice["code"] == code:
                    raise TroupeError(
                        "artifact.write-failed",
                        problem="No space left on device.",
                        fix="Free some.",
                    )
            return original(events, lineage, **kwargs)

        store.record_with_lineage = record
        return store

    return wrap


def test_a_notice_that_cant_be_recorded_cancels_the_run_and_its_end_names_the_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusing_scratch(monkeypatch)  # a notice raised after the failure, once the runner has ended
    harness = Harness(
        theatre(tmp_path), limits=QUICK_SILENCE, store_wrapper=failing_notice("run.silent")
    )
    with pytest.raises(TroupeError) as caught:
        harness.perform(request(script(INIT, WAIT, {"hang": True})))
    error = caught.value
    assert error.code == "run.recording-failed"
    assert error.details["notice"] == "run.silent"
    assert error.details["error"]["code"] == "artifact.write-failed"
    assert "failedAt" not in error.details
    assert "endError" not in error.details
    assert "from the notice run.silent on" in error.problem
    run_id = error.details["run"]
    # The first silence fails to record: the wait's, or one while the runner started (see
    # apart_from_silences), so init may or may not be recorded before it.
    assert shape(harness, run_id) in (["Started", "event init", "Ended"], ["Started", "Ended"])
    end = json.loads(records(harness, run_id)[-1].state)
    assert end["outcome"]["outcome"] == "cancelled"
    assert end["recording"] == {
        "notice": "run.silent",
        "error": error.details["error"],
    }
    # Every notice is still sent live, one raised after the failure too, but isn't recorded.
    assert len(live(harness, "run.silent")) >= 1
    assert len(live(harness, "run.scratch-not-removed")) == 1


def test_a_notice_after_the_runner_ends_that_cant_be_recorded_names_the_notice_not_a_seq(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusing_scratch(monkeypatch)
    harness = Harness(theatre(tmp_path), store_wrapper=failing_notice("run.scratch-not-removed"))
    with pytest.raises(TroupeError) as caught:
        harness.perform(request(script(INIT, OK)))
    error = caught.value
    assert error.details["notice"] == "run.scratch-not-removed"
    assert "failedAt" not in error.details
    assert "endError" not in error.details
    end = json.loads(records(harness, error.details["run"])[-1].state)
    assert end["recording"]["notice"] == "run.scratch-not-removed"


# Requirement: troupe masks the credential in everything it keeps from a run (notices)


def test_a_notice_holding_the_credential_is_recorded_and_sent_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusing_scratch(monkeypatch, problem=f" The key was {KEY}.")
    harness = Harness(theatre(tmp_path))
    harness.env = {**harness.env, "OPENAI_API_KEY": KEY}
    run = harness.perform(request(script(INIT, OK), runtime="openai", model="gpt-test")).run
    [noticed] = [json.loads(r.state) for r in records(harness, run.run_id) if r.topic == NOTICED]
    [sent] = live(harness, "run.scratch-not-removed")
    for notice in (noticed["notice"], sent):
        assert notice["problem"].endswith(f"The key was {MARKER}.")
        assert KEY not in json.dumps(notice)


# Design D3: one writer records the run's events and notices, in the order they arrive


def new_recorder(store: Any, run_id: str, send: Any) -> Any:  # noqa: ANN401
    """perform's recorder for a run in the theatre, outside perform: called on the event loop."""
    person = store.command(via="cli")
    agent = person.acting_as(Identity(kind="agent", id="tester", source="troupe"), via="runner")
    what = perform_module._What(
        actor="tester",
        runner="scripted",
        options={},
        effect_check=m.NoEffectCheck(),
        character=None,
        config=("sha256:" + "b" * 64,),
        workspace="theatre",
    )
    return perform_module._Recorder(
        run_id,
        what,
        store,
        person,
        agent,
        STAGE,
        "sha256:" + "a" * 64,
        send,
        asyncio.Event(),
        perform_module.ContextFull("fail", "default"),
    )


def test_notices_from_a_thread_and_the_loop_are_each_recorded_once_in_arrival_order(
    tmp_path: Path,
) -> None:
    """The recorder takes notices from the event loop and from other threads (a workspace
    operation's timer) while it records run events, and loses none, records none twice, keeps the
    order each reached the loop, records them all before the end, and sends each run event's
    update only once it is recorded."""
    store = files_service(tmp_path)
    run_id = str(uuid4())
    sent: list[Message] = []
    order: list[str] = []
    lock = threading.Lock()

    def send(update: Message) -> None:
        with lock:
            sent.append(update)

    def silent(label: str) -> Notice:
        return Notice("run.silent", problem=label, fix="Wait.", details={"seconds": 1.0})

    async def scenario() -> None:
        recorder = new_recorder(store, run_id, send)
        recorder.notice(silent("before the start"))
        order.append("before the start")
        await recorder.start({"kind": "theatre"})
        threads = []
        for seq in range(6):
            event = p.LogEvent(run_id=run_id, seq=seq, level="info", message=str(seq))
            await recorder.on_event(event)
            assert isinstance(sent[-1], m.LoggedEvent)
            assert sent[-1].seq == seq
            label = f"loop after {seq}"
            recorder.notice(silent(label))
            order.append(label)
            thread = threading.Thread(target=recorder.notice, args=(silent(f"thread {seq}"),))
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        await asyncio.sleep(0)  # let call_soon_threadsafe deliver the threads' notices
        await recorder.end(outcome("succeeded"), None)

    asyncio.run(scenario())
    stream = list(store.history(UUID(run_id)))
    assert stream[-1].topic == ENDED
    recorded = [json.loads(r.state)["notice"]["problem"] for r in stream if r.topic == NOTICED]
    threaded = [f"thread {seq}" for seq in range(6)]
    assert sorted(recorded) == sorted([*order, *threaded])  # each once, none lost
    assert [label for label in recorded if not label.startswith("thread")] == order
    assert recorded[0] == "before the start"
    assert stream[1].topic == NOTICED  # straight after the start
    reported = [json.loads(r.state)["seq"] for r in stream if r.topic == REPORTED]
    assert reported == list(range(6))


def test_a_run_events_waiter_cancelled_before_it_is_recorded_leaves_the_writer_recording(
    tmp_path: Path,
) -> None:
    """A run event whose caller stops waiting (as the run host's start timeout cancels it) is
    still recorded, and the writer goes on to record the notices after it and the end."""
    store = files_service(tmp_path)
    run_id = str(uuid4())

    async def scenario() -> None:
        recorder = new_recorder(store, run_id, lambda update: None)
        await recorder.start({"kind": "theatre"})
        event = p.LogEvent(run_id=run_id, seq=0, level="info", message="0")
        waiting = asyncio.create_task(recorder.on_event(event))
        await asyncio.sleep(0)  # the event is queued, and its caller waits for it
        waiting.cancel()
        recorder.notice(
            Notice("run.silent", problem="after", fix="Wait.", details={"seconds": 1.0})
        )
        await recorder.end(outcome("succeeded"), None)
        assert recorder.failure is None

    asyncio.run(scenario())
    topics = [record.topic for record in store.history(UUID(run_id))]
    assert topics == [STARTED, REPORTED, NOTICED, ENDED]


# Requirement: Status reads runs from a projection (a run's recorded notices)

SILENT = {
    "code": "run.silent",
    "problem": "The run has sent no event for 30s.",
    "fix": "Wait, or cancel the run if it seems stuck.",
    "details": {"seconds": 30.0},
}


def interrupted_with_a_notice(harness: Harness) -> str:
    """A run whose start, init and a run.silent notice are recorded, with no end, and whose lease
    in this clone nobody holds: its perform was killed after it fell silent."""
    store = git_service(harness.repo)
    run_id = str(uuid4())
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
    )
    person = store.command(via="cli")
    person.record(run.collect_events())
    run.report(0, {**INIT["event"], "effects": "checked", "runId": run_id, "seq": 0})
    store.command(via="runner").record(run.collect_events())
    run.notice(SILENT)
    person.record(run.collect_events())
    lease_dir(harness.repo.path, run_id).mkdir(parents=True)
    return run_id


def test_status_of_a_run_that_raised_notices_holds_them_in_order_with_their_times(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path), limits=QUICK_SILENCE)
    run_id = harness.perform(request(script(INIT, WAIT, RETRY, OK))).run.run_id
    [summary] = harness.status(run=run_id).runs
    assert summary.notices is not None
    named = shape(harness, run_id)
    assert apart_from_silences(named, after="event init") == [
        "Started",
        "event init",
        "event retry",
        "notice run.retrying",
        "event result",
        "Ended",
    ]
    recorded = [name.removeprefix("notice ") for name in named if name.startswith("notice ")]
    assert [n.notice.code for n in summary.notices] == recorded
    times = [r.lineage["at"] for r in records(harness, run_id) if r.topic == NOTICED]
    assert [n.at for n in summary.notices] == times
    check(summary.to_data(), "run.schema.json#/$defs/summary")


def test_status_of_an_interrupted_run_holds_the_notice_it_recorded(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    run_id = interrupted_with_a_notice(harness)
    result = harness.status(run=run_id)
    [summary] = result.runs
    assert summary.state == "interrupted"
    assert summary.notices is not None
    assert [n.notice.code for n in summary.notices] == ["run.silent"]
    assert [n.code for n in result.notices] == ["run.interrupted"]


def test_status_of_a_run_with_no_notices_has_no_notices_field(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    run_id = harness.perform(request(script(INIT, OK))).run.run_id
    [summary] = harness.status(run=run_id).runs
    assert summary.notices is None
    assert "notices" not in summary.to_data()


# Requirement: Logs read a run's events in order (and its recorded notices)


def test_logs_hold_a_runs_events_and_its_notices_in_recorded_order(tmp_path: Path) -> None:
    harness = Harness(theatre(tmp_path))
    run_id = harness.perform(request(script(INIT, RETRY, OK))).run.run_id
    result = harness.logs(run=run_id)
    assert [
        (entry.TYPE, entry.event.TYPE if isinstance(entry, m.LoggedEvent) else entry.notice.code)
        for entry in result.log
    ] == [
        ("event", "init"),
        ("event", "retry"),
        ("run-notice", "run.retrying"),
        ("event", "result"),
    ]
    noticed = [r for r in records(harness, run_id) if r.topic == NOTICED]
    [logged] = [entry for entry in result.log if isinstance(entry, m.LoggedNotice)]
    assert logged.at == noticed[0].lineage["at"]
    assert logged.run_id == run_id
    check(result.to_data(), "logs-result.schema.json")


def test_following_sends_a_recorded_notice_among_the_events_as_it_is_recorded(
    tmp_path: Path,
) -> None:
    """perform runs in its own process, as it does when someone follows a run from another
    terminal: two stores in one process would share the store's per-process lock."""
    repo = theatre(tmp_path)
    child = Child(repo, script(INIT, {"wait": {"ms": 1500}}, OK), silence=0.3)
    follower = Harness(repo)
    result = follower.logs(run=child.run_id, follow=True)
    assert "ENDED succeeded" in child.finish()
    followed = [
        f"{u['kind']} {u['event']['type'] if u['kind'] == 'event' else u['notice']['code']}"
        for u in follower.updates
        if u["kind"] in ("event", "run-notice")
    ]
    followed = [name.replace("run-notice ", "notice ") for name in followed]
    assert apart_from_silences(followed, after="event init") == ["event init", "event result"]
    for update in follower.updates:
        check(update, "logs-update.schema.json")
    assert result.run.state == "ended"


# Design D10: run.estimate-dropped, which estimated-cost raises through the run host, is a run's
# notice like any other


def test_a_dropped_estimate_is_recorded_as_a_notice_before_the_result_it_concerns(
    tmp_path: Path,
) -> None:
    harness = Harness(theatre(tmp_path))
    harness.env = {**harness.env, "OPENAI_API_KEY": KEY}
    estimate = {
        "event": {"type": "result", "status": "ok", "message": "done", "estimatedCostUsd": 0.5}
    }
    run = harness.perform(request(script(INIT, estimate), runtime="openai", model="gpt-test")).run
    assert run.outcome == "succeeded"
    assert shape(harness, run.run_id) == [
        "Started",
        "event init",
        "notice run.estimate-dropped",
        "event result",
        "Ended",
    ]
    [summary] = harness.status(run=run.run_id).runs
    assert [n.notice.code for n in summary.notices or []] == ["run.estimate-dropped"]
