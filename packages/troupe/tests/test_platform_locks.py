"""Tests for directory locks (spec: platform)."""

import inspect
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.files import directory_lock

HOLDER = textwrap.dedent(
    """
    import sys
    from troupe.platform.locks import hold
    with hold(sys.argv[1], timeout=10.0, announce_after=10.0):
        print("locked", flush=True)
        sys.stdin.read()
    """
)


@contextmanager
def held_by_another_process(directory: Path) -> Iterator[subprocess.Popen[str]]:
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(directory)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    assert holder.stdin is not None
    try:
        assert holder.stdout.readline().strip() == "locked"
        yield holder
    finally:
        if holder.poll() is None:
            holder.stdin.close()
        holder.wait(timeout=10)


STALL_ALLOWANCE = 30.0
"""How far past its timeout a lock wait may end on a loaded machine before it counts as a bug."""


# Requirement: Lock waits are bounded and announced


def test_waiting_for_a_lock_held_by_another_process_is_announced_then_times_out(
    tmp_path: Path,
) -> None:
    waits: list[tuple[Path, float]] = []
    with held_by_another_process(tmp_path):
        started = time.monotonic()
        with (
            pytest.raises(TroupeError) as caught,
            directory_lock(
                tmp_path, timeout=0.8, announce_after=0.2, on_wait=lambda p, w: waits.append((p, w))
            ),
        ):
            pytest.fail("the lock was taken while another process held it")
        elapsed = time.monotonic() - started
    assert caught.value.code == "lock.timeout"
    assert caught.value.path == str(tmp_path / ".lock")
    # The mechanism, exactly: one announcement, not before announce_after, then the timeout,
    # not before its time. Only the upper bound is wall-clock, with one named allowance (#100: a
    # loaded Windows machine took 10.8 s here against the 5 s bound this replaced).
    [(path, waited)] = waits
    assert path == tmp_path / ".lock"
    assert 0.2 <= waited <= elapsed
    assert 0.8 <= elapsed < 0.8 + STALL_ALLOWANCE


def test_the_lock_can_be_taken_once_the_other_process_releases_it(tmp_path: Path) -> None:
    with held_by_another_process(tmp_path) as holder:
        assert holder.stdin is not None
        holder.stdin.close()
        with directory_lock(tmp_path, timeout=5.0, announce_after=5.0) as lock_path:
            assert lock_path == tmp_path / ".lock"


def test_a_lock_held_by_a_process_that_dies_is_released_by_the_os(tmp_path: Path) -> None:
    with held_by_another_process(tmp_path) as holder:
        holder.kill()
        holder.wait(timeout=10)
        with directory_lock(tmp_path, timeout=5.0, announce_after=5.0):
            pass


def test_lock_timeout_defaults_come_from_troupe_core_defaults() -> None:
    parameters = inspect.signature(directory_lock).parameters
    assert parameters["timeout"].default == defaults.LOCK_TIMEOUT_SECONDS
    assert parameters["announce_after"].default == defaults.LOCK_ANNOUNCE_AFTER_SECONDS


def test_the_lock_leaves_only_an_empty_lock_file_behind(tmp_path: Path) -> None:
    with directory_lock(tmp_path):
        pass
    assert [p.name for p in tmp_path.iterdir()] == [".lock"]
    assert (tmp_path / ".lock").read_bytes() == b""


# Requirement: A process cannot deadlock on its own lock


def test_taking_a_lock_this_process_already_holds_fails_immediately(tmp_path: Path) -> None:
    with directory_lock(tmp_path):
        started = time.monotonic()
        with pytest.raises(TroupeError) as caught, directory_lock(tmp_path, timeout=5.0):
            pytest.fail("the lock was taken twice")
        assert time.monotonic() - started < 0.5
    assert caught.value.code == "lock.already-held"
    with directory_lock(tmp_path):  # still usable after the refusal
        pass


class _StallingClock:
    """time.monotonic on a machine that stalls for ``stall`` seconds after the first look."""

    def __init__(self, stall: float) -> None:
        self.now = 1000.0
        self.stall = stall
        self.looks = 0

    def __call__(self) -> float:
        self.looks += 1
        if self.looks == 2:
            self.now += self.stall
        return self.now


def test_a_stall_past_the_timeout_still_announces_the_wait_before_giving_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A loaded machine can stall a waiter past its timeout before its first announcement
    # (#100: a lock wait took 10.8 s against a 0.8 s timeout). It must still not end silently.
    from troupe.platform import locks
    from troupe.platform.errors import LockTimeoutError

    waits: list[tuple[Path, float]] = []
    with held_by_another_process(tmp_path):
        monkeypatch.setattr(time, "monotonic", _StallingClock(10.0))
        monkeypatch.setattr(time, "sleep", lambda seconds: None)
        with (
            pytest.raises(LockTimeoutError),
            locks.hold(
                tmp_path, timeout=0.8, announce_after=0.2, on_wait=lambda p, w: waits.append((p, w))
            ),
        ):
            pytest.fail("the lock was taken while another process held it")
    assert [(path, waited) for path, waited in waits] == [(tmp_path / ".lock", 10.0)]
