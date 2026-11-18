"""The event store port's subscription (spec: event-store, "A subscription delivers other writers'
events as they're recorded"; watch-event-segments design D0, D7).

The guarantee is the port's, so this test reaches the store only as troupe.core does: by name,
through the port, with its defaults. It knows nothing of files or watching, so any store is held
to it. A store that only polls, every SUBSCRIBE_POLL_SECONDS, can't pass: see ``Notified``.
"""

import math
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from storetesting import BOUND, STALL_SECONDS, watched_delays
from troupe.core import defaults
from troupe.core.events import load_store
from troupe.core.vcs import load_vcs

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

HEARD_WITHIN = defaults.SUBSCRIBE_CHECK_SECONDS + STALL_SECONDS
"""How long one delivery may take before the store counts as not delivering. A report the OS drops
or holds back, as FSEvents can under load, is delivered by the store's check, every
SUBSCRIBE_CHECK_SECONDS (watch-event-segments D5), so through the port's defaults a delivery can
lawfully take that long (#448, load-flakes design D3). A late delivery is one slow sample; the
fastest must still be under BOUND."""


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


class Notified(threading.Event):
    """A listener that keeps the wall-clock time of each notification.

    A store that only polls notifies at most once per SUBSCRIBE_POLL_SECONDS: its next look starts
    a full interval after the look that last notified. So an event recorded ``lead`` seconds after
    the last notification reaches it no sooner than SUBSCRIBE_POLL_SECONDS - ``lead`` later. Only
    a delivery whose event was recorded less than SUBSCRIBE_POLL_SECONDS - BOUND after the last
    notification counts towards the bound, so a poller's can never be under it, however the
    writer is scheduled (load-flakes design D4). Each record follows a notification by about
    0.1 s, the writer's own pause, so on a working store nearly every delivery counts."""

    def __init__(self) -> None:
        super().__init__()
        self.times: list[float] = []

    def set(self) -> None:
        self.times.append(time.time())
        super().set()

    def counts(self, recorded: float) -> bool:
        """Whether a delivery of an event recorded at ``recorded`` counts towards the bound."""
        before = [at for at in self.times if at <= recorded]
        return bool(before) and recorded - max(before) < defaults.SUBSCRIBE_POLL_SECONDS - BOUND


def test_another_writers_events_reach_a_port_subscriber_the_fastest_under_the_bound(
    tmp_path: Path, writer: subprocess.Popen[str]
) -> None:
    assert defaults.SUBSCRIBE_POLL_SECONDS - BOUND >= 0.5  # room for the writer's 0.1 s pause
    record(writer)  # the store exists before subscribing
    store = load_store("text", tmp_path, load_vcs("files", tmp_path))
    heard = Notified()
    store.listen(heard)
    delays: list[float] = []
    try:
        time.sleep(0.5)  # a fresh subscription may wake once on its own
        recorded_count = 1

        def measure() -> float:
            """The delay, for watched_delays to sample, or inf when it doesn't count."""
            nonlocal recorded_count
            heard.clear()
            assert writer.stdin is not None
            writer.stdin.write("record\n")
            writer.stdin.flush()
            assert heard.wait(HEARD_WITHIN), f"no delivery within {HEARD_WITHIN} s"
            woke = time.time()
            assert writer.stdout is not None
            recorded = float(writer.stdout.readline().split()[1])
            recorded_count += 1
            assert store.max_notification_id() == recorded_count
            delays.append(woke - recorded)
            return delays[-1] if heard.counts(recorded) else math.inf

        counted = watched_delays(measure)
    finally:
        store.unlisten(heard)
    assert min(counted) < BOUND, (counted, delays)
    assert statistics.median(delays[:5]) < BOUND + STALL_SECONDS, delays
