"""Finding, starting and stopping Claude Code's process, on every platform (design D6, D7, D9)."""

import os
import stat
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
    shim.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    child = processes.start([str(shim)], tmp_path, dict(os.environ))
    deadline = time.monotonic() + MARGIN
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pid_file.exists(), "the shim never started its grandchild"
    grandchild = int(pid_file.read_text())
    child.stop(STOP_GRACE)
    child.release()
    assert not _alive(grandchild)


def test_find_claude_finds_the_program_on_an_absolute_path_entry(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    name = "claude.cmd" if sys.platform == "win32" else "claude"
    program = bin_dir / name
    program.write_text("@echo off\r\n" if sys.platform == "win32" else "#!/bin/sh\n")
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    found = processes.find_claude(os.pathsep.join([str(tmp_path / "empty"), str(bin_dir)]))
    assert found is not None
    assert found.parent == bin_dir
    assert found.name.lower() == name


def test_find_claude_skips_relative_and_empty_path_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "claude").write_text("#!/bin/sh\n")
    (tmp_path / "claude").chmod(0o755)
    (tmp_path / "claude.cmd").write_text("@echo off\r\n")
    monkeypatch.chdir(tmp_path)
    assert processes.find_claude(os.pathsep.join(["", ".", "relative"])) is None


def test_find_claude_finds_nothing_without_a_path() -> None:
    assert processes.find_claude(None) is None
    assert processes.find_claude("") is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX needs the executable bit")
def test_find_claude_skips_a_file_that_isnt_executable_on_posix(tmp_path: Path) -> None:
    (tmp_path / "claude").write_text("#!/bin/sh\n")
    (tmp_path / "claude").chmod(0o644)
    assert processes.find_claude(str(tmp_path)) is None


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (0, 0),
        (1, 1),
        (143, 143),
        (255, 255),
        (-15, 143),
        (-9, 137),
        (0x74726B6C, 1),
        (-1073741510, 1),
    ],
)
def test_exit_code_maps_claude_codes_status_onto_the_runners_exit_code(
    status: int, code: int
) -> None:
    assert processes.exit_code(status) == code
