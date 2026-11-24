"""Tests for directory locks (spec: platform).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_platform_locks.py."""

import inspect
import time
from pathlib import Path

import pytest

from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.files import directory_lock


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
