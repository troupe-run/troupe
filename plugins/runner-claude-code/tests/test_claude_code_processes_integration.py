"""Finding, starting and stopping Claude Code's process, on every platform (design D6, D7, D9).

Its tests that stay in their own process are in unit/test_claude_code_processes.py."""

import os
import sys
import time
from pathlib import Path

import pytest

from troupe_runner_claude_code import processes

STOP_GRACE = 2.0
MARGIN = 10.0
"""Room for a loaded CI worker on top of the grace: a stop must end well inside it."""


def _alive(pid: int) -> bool:
    """Whether ``pid`` names a running process, without a platform module of troupe's."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)
        if not handle:
            return False
        try:
            return bool(kernel32.WaitForSingleObject(handle, 0) == 0x102)
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers kill(pid, 0); the caller has reaped its own child already.
    return True


def _python(code: str, tmp_path: Path) -> processes.Claude:
    return processes.start([sys.executable, "-c", code], tmp_path, dict(os.environ))


def test_stop_ends_a_child_that_honours_the_polite_stop(tmp_path: Path) -> None:
    child = _python("import time; time.sleep(60)", tmp_path)
    started = time.monotonic()
    status = child.stop(STOP_GRACE)
    child.release()
    assert time.monotonic() - started < STOP_GRACE + MARGIN
    assert status != 0
    assert not _alive(child.pid)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no SIGTERM to ignore")
def test_stop_kills_a_posix_child_that_ignores_sigterm_after_the_grace(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    child = _python(
        "import signal, sys, time, pathlib\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"pathlib.Path({str(ready)!r}).write_text('ok')\n"
        "time.sleep(60)\n",
        tmp_path,
    )
    deadline = time.monotonic() + MARGIN
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists(), "the child never installed its SIGTERM handler"
    started = time.monotonic()
    status = child.stop(STOP_GRACE)
    elapsed = time.monotonic() - started
    assert elapsed >= STOP_GRACE
    assert elapsed < STOP_GRACE + MARGIN
    assert status == -9
    assert not _alive(child.pid)


@pytest.mark.skipif(sys.platform != "win32", reason="the job only exists on Windows")
def test_stop_on_windows_ends_the_grandchild_a_cmd_shim_starts(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    script = tmp_path / "grandchild.py"
    script.write_text(
        "import os, pathlib, time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    shim = tmp_path / "claude.cmd"
    # The base interpreter, not the venv's python.exe: that is a launcher whose own job holds the
    # real interpreter, so the pid the child reports would be a process the launcher ends.
    shim.write_text(
        f'@"{getattr(sys, "_base_executable", sys.executable)}" "{script}" %*\r\n', encoding="utf-8"
    )
    child = processes.start([str(shim)], tmp_path, dict(os.environ))
    assert child._job is not None, "Claude Code wasn't given a job of its own"  # a precondition
    deadline = time.monotonic() + MARGIN
    while not (pid_file.exists() and pid_file.read_text()) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pid_file.exists(), "the shim never started its grandchild"
    grandchild = int(pid_file.read_text())
    assert _alive(grandchild), "the grandchild ended before the stop"  # a precondition
    started = time.monotonic()
    child.stop(STOP_GRACE)
    stopped = time.monotonic() - started
    alive_after_stop = _alive(grandchild)
    child.release()
    later = time.monotonic() + MARGIN
    while _alive(grandchild) and time.monotonic() < later:
        time.sleep(0.05)
    assert not alive_after_stop, (
        f"the grandchild {grandchild} was alive after a stop of {stopped:.2f}s; "
        f"{'it ended within' if not _alive(grandchild) else 'it was still alive after'} "
        f"{MARGIN:g}s more"
    )
