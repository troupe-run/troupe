"""A run's notices are kept in its history (spec: runs, client-protocol; run-notices-in-history
design D2 to D8).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_run_notices.py."""

import asyncio
import importlib
import json
import threading
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from configtesting import TESTER
from runtesting import PERFORMANCE, STAGE, outcome
from storetesting import files_service
from troupe.core.client import messages as m
from troupe.core.config.changes import change
from troupe.core.config.stream import read as read_config
from troupe.core.config.stream import record as record_config
from troupe.core.identity import Identity
from troupe.core.notices import Notice
from troupe.core.runs.aggregate import (
    ENDED,
    NOTICED,
    REPORTED,
    STARTED,
)
from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.messages import Message

# troupe.core.runs re-exports perform the function, so the modules are reached by name.
perform_module = importlib.import_module("troupe.core.runs.perform")

# Design D3: one writer records the run's events and notices, in the order they arrive


def new_recorder(store: Any, run_id: str, send: Any) -> Any:  # noqa: ANN401
    """perform's recorder for a run in the theatre, outside perform: called on the event loop."""
    person = store.command(via="cli")
    agent = person.acting_as(Identity(kind="agent", id="tester", source="troupe"), via="runner")
    in_performance = person.in_performance(PERFORMANCE)
    # A real config version: a run's start requires its config heads to be here
    # (abandoned-edits design D4).
    merged = read_config(store)
    if not merged.heads:
        record_config(person, merged, change(merged.config, [(("actors", "tester"), TESTER)]), [])
        merged = read_config(store)
    what = perform_module._What(
        actor="tester",
        runner="scripted",
        options={},
        effect_check=m.NoEffectCheck(),
        character=None,
        config=tuple(merged.heads),
        workspace="theatre",
    )
    return perform_module._Recorder(
        PERFORMANCE,
        run_id,
        what,
        store,
        in_performance,
        agent.in_performance(PERFORMANCE),
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
