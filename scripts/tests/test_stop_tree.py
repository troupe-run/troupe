"""stop_tree (scripts/tests/conftest.py): a test that gives up on a process stops its whole tree,
however its descendants are grouped (#364)."""

import json
import subprocess
import sys
import time
from pathlib import Path

from conftest import run_with_progress, run_within, stop_tree

from troupe.platform.processes import is_running

GONE_WITHIN = 10.0
"""Seconds for a killed process to be gone, with room for a loaded machine to reap it."""
STARTED_WITHIN = 60.0
"""Seconds for the child to start its two descendants on a slow machine."""

CHILD = """
import json, subprocess, sys, time
from pathlib import Path

windows = sys.platform == "win32"
# A sleeper in a session of its own, as a flake hunt's round is, and a spinning load beside it.
apart = {"creationflags": 0x00000200} if windows else {"start_new_session": True}
sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], **apart)
load = subprocess.Popen([sys.executable, "-c", "while True: pass"])
Path(sys.argv[1]).write_text(json.dumps([sleeper.pid, load.pid]))
time.sleep(120)
"""


def test_stopping_a_tree_stops_descendants_in_other_sessions_and_spinning_ones(
    tmp_path: Path,
) -> None:
    pids_file = tmp_path / "pids.json"
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(pids_file)])
    descendants: list[int] = []
    try:
        deadline = time.monotonic() + STARTED_WITHIN
        while not (pids_file.exists() and pids_file.read_text()):
            assert time.monotonic() < deadline, "the child never started its descendants"
            time.sleep(0.05)
        descendants = json.loads(pids_file.read_text())
        assert all(is_running(pid) for pid in descendants)
    finally:
        stop_tree(child)
    deadline = time.monotonic() + GONE_WITHIN
    while (left := [pid for pid in descendants if is_running(pid)]) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert left == [], f"{left} outlived stop_tree"
    assert child.returncode is not None


# run_with_progress: a command's bound is the time between its lines, not its whole run (#397)

TICKING = """
import time
for i in range(12):
    print(f"tick {i}", flush=True)
    time.sleep(0.5)
"""
"""Prints a line every 0.5 s for about 6 s: always making progress, never within 5 s overall."""

STALLING = "import time\nprint('started', flush=True)\ntime.sleep(60)\n"
"""Prints one line, then makes no progress."""

EACH_WITHIN = 5.0
"""The tests' bound: past the ticker's 0.5 s between lines, and room for a loaded machine to start
Python before its first line (review of #437)."""


def test_a_command_making_progress_passes_a_per_line_bound_shorter_than_its_whole_run() -> None:
    command = [sys.executable, "-c", TICKING]
    completed = run_with_progress(command, EACH_WITHIN)
    assert completed.returncode == 0
    assert completed.stdout.decode().splitlines()[-1] == "tick 11"
    try:
        run_within(command, EACH_WITHIN)  # the fixed whole-run bound #397 replaces gives up on it
    except AssertionError:
        pass
    else:
        raise AssertionError("run_within(5 s) should have stopped a 6 s command")


def test_a_command_that_stops_making_progress_fails_naming_its_last_line() -> None:
    started = time.monotonic()
    try:
        stalling = [sys.executable, "-c", STALLING]
        run_with_progress(stalling, EACH_WITHIN, waiting_for="the next line")
    except AssertionError as error:
        message = str(error)
    else:
        raise AssertionError("a stalled command should fail")
    assert time.monotonic() - started < 30  # stopped at the bound, not at the sleep's end
    assert f"wrote no line within {EACH_WITHIN:g}s" in message
    assert "the next line" in message
    assert "'started'" in message
