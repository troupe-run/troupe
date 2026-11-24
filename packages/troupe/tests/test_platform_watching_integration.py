"""Watching a directory (platform/watching.py; spec: platform; watch-event-segments design D2, D7).

Its tests that stay in their own process are in unit/test_platform_watching.py."""

import statistics
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from platform_watching_shared import drain, settled
from storetesting import BOUND, SLOW_STRETCH_SECONDS, STALL_SECONDS, WITHIN, watched_delays

TESTS_ROOT = next(p for p in Path(__file__).resolve().parents if p.name == "tests")
"""This suite's tests directory, found by name so the file can sit at any depth under it."""

CHILD = TESTS_ROOT / "watch_child.py"


class Changer:
    """watch_child.py, changing files on command."""

    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(CHILD)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

    def send(self, command: str, path: Path) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(f"{command} {path}\n")
        self.process.stdin.flush()

    def done_at(self) -> float:
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        assert line.startswith("DONE "), line
        return float(line.split()[1])

    def close(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        assert self.process.wait(timeout=30) == 0


@pytest.fixture
def changer() -> Iterator[Changer]:
    child = Changer()
    yield child
    child.close()


def test_another_processs_appends_each_wake_a_wait_the_fastest_under_the_bound(
    tmp_path: Path, changer: Changer
) -> None:
    segment = tmp_path / "segment.jsonl"
    segment.write_bytes(b"")
    with settled(tmp_path) as watched:

        def measure() -> float:
            changer.send("append", segment)
            assert watched.wait(WITHIN)
            woke = time.time()
            delay = woke - changer.done_at()
            drain(watched)
            return delay

        delays = watched_delays(measure)
    assert min(delays) < BOUND, delays
    assert statistics.median(delays[:5]) < BOUND + STALL_SECONDS, delays


def test_another_processs_new_file_wakes_a_wait(tmp_path: Path, changer: Changer) -> None:
    with settled(tmp_path) as watched:
        changer.send("create", tmp_path / "new.jsonl")
        assert watched.wait(WITHIN)
        changer.done_at()


def test_another_processs_removing_a_file_wakes_a_wait(tmp_path: Path, changer: Changer) -> None:
    doomed = tmp_path / "doomed.jsonl"
    doomed.write_bytes(b"x\n")
    with settled(tmp_path) as watched:
        changer.send("remove", doomed)
        assert watched.wait(WITHIN)
        changer.done_at()


def test_a_change_made_while_nobody_waits_is_reported_by_the_next_wait_at_once(
    tmp_path: Path, changer: Changer
) -> None:
    # "At once" is checked with a zero timeout, not a clock, so a stalled thread can't fail it
    # (#446, load-flakes design D2). Load can still make the OS deliver the change after the quiet
    # half second; then a wait with a timeout must still report it, and the next change is tried,
    # until one is reported with no waiting or the slow stretch's budget is spent. A wait that
    # blocks on a pending change, or that only notices changes while someone waits, fails every try.
    segment = tmp_path / "segment.jsonl"
    segment.write_bytes(b"")
    with settled(tmp_path) as watched:

        def reported_without_waiting() -> bool:
            changer.send("append", segment)
            changer.done_at()
            time.sleep(0.5)  # the change is made, and delivered, while nobody waits
            at_once = watched.wait(0)
            if not at_once:
                assert watched.wait(WITHIN), "a change made while nobody waited was lost"
            drain(watched)
            return at_once

        started = time.monotonic()
        tries = [reported_without_waiting()]
        while not tries[-1] and time.monotonic() - started < SLOW_STRETCH_SECONDS:
            tries.append(reported_without_waiting())
    assert tries[-1], f"no zero-timeout wait reported its change in {len(tries)} tries"


def test_a_directory_of_10000_files_is_watched_within_a_256_file_limit_and_wakes_on_one_growing(
    tmp_path: Path,
) -> None:
    for number in range(10_000):
        (tmp_path / f"{number:05}.jsonl").write_bytes(b"")
    watcher = subprocess.Popen(
        [sys.executable, str(CHILD), "watch", str(tmp_path), "256"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert watcher.stdout is not None
    ready = watcher.stdout.readline()
    assert ready == "READY\n", (ready, watcher.stderr.read() if watcher.stderr else "")
    with (tmp_path / "04321.jsonl").open("ab") as segment:
        segment.write(b"grown\n")
    out, err = watcher.communicate(timeout=30)
    assert out == "CHANGED\n", err
