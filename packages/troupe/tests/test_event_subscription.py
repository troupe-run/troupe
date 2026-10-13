"""The event store port's subscription (spec: event-store, "A subscription delivers other writers'
events as they're recorded"; watch-event-segments design D0, D7).

The guarantee is the port's, so this test reaches the store only as troupe.core does: by name,
through the port, with its defaults. It knows nothing of files or watching, so any store is held
to it. A store that could only poll at SUBSCRIBE_POLL_SECONDS (1 s) would give a median delay near
half a second, and fail.
"""

import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from troupe.core import defaults
from troupe.core.events import load_store
from troupe.core.vcs import load_vcs

BOUND = 0.25  # seconds

WRITER = """
import sys, time
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, {tests!r})
from storetesting import event
from troupe.core.events import load_store
from troupe.core.vcs import load_vcs

theatre = Path({theatre!r})
store = load_store("text", theatre, load_vcs("files", theatre))
stream = uuid4()
for version, _ in enumerate(sys.stdin, start=1):
    time.sleep(0.1)
    store.insert([event(stream, version)])
    print("RECORDED", repr(time.time()), flush=True)
"""
"""Records one event through the port per line read, printing when each call to record returned.
The record call returns after the write, so timing from it can only shorten the measured delay."""


@pytest.fixture
def writer(tmp_path: Path) -> Iterator[subprocess.Popen[str]]:
    code = WRITER.format(tests=str(Path(__file__).parent), theatre=str(tmp_path))
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    yield process
    assert process.stdin is not None
    process.stdin.close()
    assert process.wait(timeout=30) == 0


def record(writer: subprocess.Popen[str]) -> float:
    assert writer.stdin is not None
    assert writer.stdout is not None
    writer.stdin.write("record\n")
    writer.stdin.flush()
    line = writer.stdout.readline()
    assert line.startswith("RECORDED "), (line, writer.stderr.read() if writer.stderr else "")
    return float(line.split()[1])


def test_another_writers_events_reach_a_port_subscriber_with_a_median_delay_under_the_bound(
    tmp_path: Path, writer: subprocess.Popen[str]
) -> None:
    assert defaults.SUBSCRIBE_POLL_SECONDS >= 4 * BOUND  # polling alone can't pass
    record(writer)  # the store exists before subscribing
    store = load_store("text", tmp_path, load_vcs("files", tmp_path))
    heard = threading.Event()
    delays: list[float] = []
    store.listen(heard)
    try:
        time.sleep(0.5)  # a fresh subscription may wake once on its own
        for count in range(2, 7):
            heard.clear()
            assert writer.stdin is not None
            writer.stdin.write("record\n")
            writer.stdin.flush()
            assert heard.wait(10)
            woke = time.time()
            assert writer.stdout is not None
            recorded = float(writer.stdout.readline().split()[1])
            delays.append(woke - recorded)
            assert store.max_notification_id() == count
    finally:
        store.unlisten(heard)
    assert statistics.median(delays) < BOUND, delays
