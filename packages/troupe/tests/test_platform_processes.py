"""Tests for child processes (spec: platform)."""

import asyncio
import contextlib
import errno
import json
import os
import re
import shutil
import subprocess
import sys
import time
import typing
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from troupe.platform import processes
from troupe.platform.errors import (
    CommandNotFoundError,
    LineTooLongError,
    OutputTooLargeError,
    ProcessStateUnknownError,
    ProcessTimeoutError,
)

WINDOWS = sys.platform == "win32"
LIMIT = 8 * 1024 * 1024

ADDED_BY_THE_INTERPRETER = {"LC_CTYPE", "__CF_USER_TEXT_ENCODING", "__PYVENV_LAUNCHER__"}
"""Variables a Python child sets in its own environment at start-up (locale coercion, macOS
CoreFoundation, the Windows venv launcher), so they are not evidence of inheritance."""


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


async def _output(child: processes.ChildProcess) -> bytes:
    out = await child.stdout.read()
    await child.wait()
    child.release()
    return out


def _child_environment(env: dict[str, str]) -> dict[str, str]:
    async def main() -> bytes:
        child = await processes.start(
            _python("import json, os; print(json.dumps(dict(os.environ)))"),
            cwd=Path.cwd(),
            env=env,
            line_limit=LIMIT,
        )
        return await _output(child)

    seen: dict[str, str] = json.loads(asyncio.run(main()))
    return seen


# Requirement: Child processes start in their own group with an explicit environment


def test_a_child_sees_the_named_variable_and_none_of_the_parents_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TROUPE_TEST_HOST_SECRET", "must-not-leak")
    seen = _child_environment({"TROUPE_TEST_NAMED": "passed"})
    assert seen["TROUPE_TEST_NAMED"] == "passed"
    assert "TROUPE_TEST_HOST_SECRET" not in seen
    unexpected = set(seen) - {"TROUPE_TEST_NAMED", *processes.MINIMUM_ENVIRONMENT}
    assert unexpected <= ADDED_BY_THE_INTERPRETER


def test_a_python_child_starts_and_runs_with_no_named_variables() -> None:
    seen = _child_environment({})
    assert set(seen) - set(processes.MINIMUM_ENVIRONMENT) <= ADDED_BY_THE_INTERPRETER
    if WINDOWS:
        assert "SYSTEMROOT" in seen


def test_a_missing_command_is_reported_by_name() -> None:
    async def main() -> None:
        await processes.start(["troupe-no-such-runner"], cwd=Path.cwd(), env={}, line_limit=LIMIT)

    with pytest.raises(CommandNotFoundError) as caught:
        asyncio.run(main())
    assert caught.value.command == "troupe-no-such-runner"


def test_the_command_is_found_on_the_given_search_path(tmp_path: Path) -> None:
    found = processes.resolve_command(Path(sys.executable).name, str(Path(sys.executable).parent))
    assert Path(found).is_absolute()
    with pytest.raises(CommandNotFoundError):
        processes.resolve_command(Path(sys.executable).name, str(tmp_path))


# Requirement: Killing a child kills its whole process tree

GRANDPARENT = """
import subprocess, sys, time
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(grandchild.pid, flush=True)
time.sleep(120)
"""


def _gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not processes.is_running(pid):
            return True
        time.sleep(0.05)
    return False


def test_killing_a_child_also_kills_the_grandchild_it_started() -> None:
    async def main() -> tuple[int, int]:
        child = await processes.start(
            _python(GRANDPARENT), cwd=Path.cwd(), env={}, line_limit=LIMIT
        )
        grandchild = int(await asyncio.wait_for(child.stdout.readline(), timeout=30))
        assert processes.is_running(grandchild)
        child.kill_tree()
        await asyncio.wait_for(child.wait(), timeout=30)
        child.kill_tree()  # a second kill is harmless
        child.release()
        return child.pid, grandchild

    child_pid, grandchild_pid = asyncio.run(main())
    assert _gone_within(child_pid, 10)
    assert _gone_within(grandchild_pid, 10)


ESCAPE_WINDOW = 5.0
"""How long the hook holds the moment between starting a child and putting it in its job open,
waiting for the child to start a grandchild. A child that runs in that moment does so well within
it; a suspended one never does, and the hook gives up."""
WAIT_LIMIT = 30.0
"""How long waiting for a killed child may take before the test fails instead of hanging (#187)."""


def _early_grandparent(marker: Path) -> str:
    """A child whose first act is to start a grandchild that holds its output open, writing the
    grandchild's pid to ``marker`` and to standard output."""
    return (
        "import pathlib, subprocess, sys, time\n"
        'grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
        f"pathlib.Path({str(marker)!r}).write_text(str(grandchild.pid))\n"
        "print(grandchild.pid, flush=True)\n"
        "time.sleep(60)\n"
    )


def _hold_the_job_assignment_open(marker: Path) -> Callable[[int], None]:
    """A hook that waits, before the job is assigned, for the child to report a grandchild."""

    def hold(pid: int) -> None:
        deadline = time.monotonic() + ESCAPE_WINDOW
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)

    return hold


def _end_if_running(pid: int) -> None:
    """Best-effort cleanup of a grandchild that escaped, so a failure doesn't leave it running."""
    if processes.is_running(pid):
        with contextlib.suppress(OSError):
            os.kill(pid, 9)  # SIGKILL on POSIX; TerminateProcess with code 9 on Windows


def test_a_grandchild_started_before_the_child_could_be_put_in_its_job_is_killed_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "grandchild.pid"
    monkeypatch.setattr(processes, "_before_job_assignment", _hold_the_job_assignment_open(marker))

    async def main() -> int:
        child = await processes.start(
            _python(_early_grandparent(marker)), cwd=Path.cwd(), env={}, line_limit=LIMIT
        )
        grandchild = int(await asyncio.wait_for(child.stdout.readline(), timeout=WAIT_LIMIT))
        child.kill_tree()
        try:
            await asyncio.wait_for(child.wait(), timeout=WAIT_LIMIT)
        except TimeoutError:
            _end_if_running(grandchild)
            pytest.fail(
                f"waiting for the killed child took over {WAIT_LIMIT:g}s: grandchild {grandchild} "
                f"is {'still running' if processes.is_running(grandchild) else 'gone'}, holding "
                "the child's output open"
            )
        finally:
            child.release()
        return grandchild

    grandchild = asyncio.run(main())
    gone = _gone_within(grandchild, 10)
    _end_if_running(grandchild)
    assert gone, f"grandchild {grandchild} outlived the kill: it escaped the child's job"


def test_closing_stdin_lets_a_child_read_end_of_file() -> None:
    async def main() -> bytes:
        child = await processes.start(
            _python("import sys; print(len(sys.stdin.read()))"),
            cwd=Path.cwd(),
            env={},
            line_limit=LIMIT,
        )
        child.stdin.write(b"abc")
        await child.stdin.drain()
        child.close_stdin()
        return await asyncio.wait_for(_output(child), timeout=30)

    assert asyncio.run(main()).strip() == b"3"


# Requirement: A child's end says whether troupe's kill ended it

KILL_STATUS = processes.KILLED_EXIT_CODE if WINDOWS else -9
"""The exit status troupe's kill gives a child: its named code on Windows, SIGKILL elsewhere."""

ENDS_ITSELF_LIKE_A_KILL = (
    f"import os; os._exit({KILL_STATUS})"
    if WINDOWS
    else "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"
)


def _ended(code: str, *, kill: bool) -> tuple[int, bool]:
    """Start a child, kill it once it has said it is running (when ``kill``), and return its exit
    code and whether the seam says the kill ended it."""

    async def main() -> tuple[int, bool]:
        child = await processes.start(_python(code), cwd=Path.cwd(), env={}, line_limit=LIMIT)
        try:
            await asyncio.wait_for(child.stdout.readline(), timeout=30)
            if kill:
                child.kill_tree()
            exit_code = await asyncio.wait_for(child.wait(), timeout=30)
            return exit_code, child.ended_by_kill(exit_code)
        finally:
            child.kill_tree()
            await child.wait()
            child.release()

    return asyncio.run(main())


def test_a_running_child_troupe_killed_was_ended_by_the_kill() -> None:
    exit_code, by_kill = _ended("import time; print('up', flush=True); time.sleep(120)", kill=True)
    assert (exit_code, by_kill) == (KILL_STATUS, True)


EXITS_WHEN_TOLD = """
import os, sys, time
print("up", flush=True)
deadline = time.monotonic() + 10
while not os.path.exists(sys.argv[1]):
    if time.monotonic() > deadline:
        sys.exit(3)
    time.sleep(0.01)
"""
"""A child that says it's running, then exits 0 once the file named by its argument exists, or 3
if it hasn't appeared within 10 s. It exits when the test says, not after a sleep. Its 10 s sits
well inside EXIT_BOUND_SECONDS, so a child that's never told ends with its own code first."""


EXIT_BOUND_SECONDS = 30.0
"""How long the race test waits for its child to exit at the OS level before it fails."""


def _precondition(problem: str) -> typing.NoReturn:
    """Fail the race test because the race it needs wasn't set up, which says nothing about the
    seam. The prefix keeps it from being read as a wrong answer about the kill."""
    pytest.fail(f"precondition not reached: {problem}", pytrace=False)


def _not_exited(pid: int) -> typing.NoReturn:
    _precondition(f"the child ({pid}) did not exit within {EXIT_BOUND_SECONDS} s of being told to")


# Each _exit_of watches one child's exit at the OS level, without the seam under test, and yields
# a wait that returns the exit status the OS recorded, or None where asyncio's watcher has already
# taken it. Nothing in it yields to the event loop, so asyncio can't record the exit meanwhile.
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _SYNCHRONIZE = 0x00100000
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _WAIT_OBJECT_0 = 0
    _WAIT_TIMEOUT = 0x102

    def _windows_error(doing: str) -> typing.NoReturn:
        _precondition(f"{doing} failed: {ctypes.WinError(ctypes.get_last_error())}")

    @contextlib.contextmanager
    def _exit_of(pid: int) -> Iterator[Callable[[], int | None]]:
        """A handle opened now, while the child runs, pins that process, so a reused pid can't
        stand in for it. Waiting on it is one answer: exited, or not within the bound."""
        handle = _kernel32.OpenProcess(
            _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            _windows_error(f"opening the child ({pid}) to watch its exit")

        def wait() -> int | None:
            waited = _kernel32.WaitForSingleObject(handle, int(EXIT_BOUND_SECONDS * 1000))
            if waited == _WAIT_TIMEOUT:
                _not_exited(pid)
            if waited != _WAIT_OBJECT_0:
                _windows_error(f"waiting for the child ({pid}) to exit")
            code = wintypes.DWORD()
            if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                _windows_error(f"reading the child's ({pid}) exit code")
            return int(code.value)

        try:
            yield wait
        finally:
            _kernel32.CloseHandle(handle)

elif hasattr(os, "waitid"):
    # Chosen by what os offers, not the platform: who reaps the child depends on the Python
    # version (python-3-14-3-15 design D2). Linux's pidfd watcher, and the threaded watcher on
    # macOS from 3.14, reap on the loop, so a blocked loop leaves a zombie whose status waitid
    # reads. On macOS 3.13 the watcher thread reaps, and waitid says so with ChildProcessError.

    class _Waited(typing.Protocol):
        si_code: int
        si_status: int

    # typeshed declares waitid for Linux only, but macOS has it from Python 3.13.
    _waitid = typing.cast(
        Callable[[int, int, int], _Waited | None],
        getattr(os, "waitid"),  # noqa: B009
    )

    @contextlib.contextmanager
    def _exit_of(pid: int) -> Iterator[Callable[[], int | None]]:
        """waitid without reaping, polled to the bound: the status is there to read until the
        loop reaps, unless a watcher thread already has."""

        def wait() -> int | None:
            deadline = time.monotonic() + EXIT_BOUND_SECONDS
            while True:
                try:
                    seen = _waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
                except ChildProcessError:
                    return None  # a watcher thread reaped it, which only an exit allows
                if seen is not None:
                    return seen.si_status if seen.si_code == os.CLD_EXITED else -seen.si_status
                if time.monotonic() >= deadline:
                    _not_exited(pid)
                time.sleep(0.01)

        yield wait

else:
    # No waitid: macOS on 3.12, where asyncio's watcher thread reaps the child itself.

    @contextlib.contextmanager
    def _exit_of(pid: int) -> Iterator[Callable[[], int | None]]:
        """asyncio's watcher thread reaps the child but can only schedule its returncode on the
        blocked loop, so the pid disappearing proves the exit. The status went to asyncio."""

        def wait() -> int | None:
            deadline = time.monotonic() + EXIT_BOUND_SECONDS
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return None
                if time.monotonic() >= deadline:
                    _not_exited(pid)
                time.sleep(0.01)

        yield wait


def test_a_kill_sent_after_the_child_exited_but_before_asyncio_saw_it_did_not_end_it(
    tmp_path: Path,
) -> None:
    told = tmp_path / "exit-now"

    async def main() -> tuple[int, bool]:
        child = await processes.start(
            [*_python(EXITS_WHEN_TOLD), str(told)], cwd=Path.cwd(), env={}, line_limit=LIMIT
        )
        try:
            await asyncio.wait_for(child.stdout.readline(), timeout=30)
            if child.returncode is not None:
                _precondition(f"the child ended ({child.returncode}) before it was told to")
            with _exit_of(child.pid) as wait_for_exit:
                # Nothing from here awaits until the kill, so the loop can't record the exit the
                # file starts, however long the child takes to see it.
                told.touch()
                own_status = wait_for_exit()
            if child.returncode is not None:
                _precondition("asyncio saw the exit before the kill, so the race was not set up")
            child.kill_tree()
            exit_code = await asyncio.wait_for(child.wait(), timeout=30)
            if own_status is None:
                # Reaped before the kill, so asyncio reports the child's own status, which the
                # kill couldn't change.
                own_status = exit_code
            if own_status != 0:
                _precondition(f"the child exited with {own_status} before the kill, not 0")
            return exit_code, child.ended_by_kill(exit_code)
        finally:
            child.kill_tree()
            await asyncio.wait_for(child.wait(), timeout=30)
            child.release()

    assert asyncio.run(main()) == (0, False)


def test_a_child_that_ends_itself_with_the_kills_status_was_not_ended_by_a_kill() -> None:
    exit_code, by_kill = _ended(f"print('up', flush=True); {ENDS_ITSELF_LIKE_A_KILL}", kill=False)
    assert (exit_code, by_kill) == (KILL_STATUS, False)


# Requirement: Child output lines are not limited to 64 KiB


def _first_line(size: int, limit: int) -> bytes:
    async def main() -> bytes:
        child = await processes.start(
            _python(f"import sys; sys.stdout.buffer.write(b'x' * {size} + b'\\n')"),
            cwd=Path.cwd(),
            env={},
            line_limit=limit,
        )
        try:
            return await processes.read_line(child.stdout, limit)
        finally:
            child.kill_tree()
            try:
                # Bounded: a refused line once left this wait hanging CI for good (#187).
                await asyncio.wait_for(child.wait(), timeout=WAIT_LIMIT)
            except TimeoutError:
                pytest.fail(f"waiting for the killed child took over {WAIT_LIMIT:g}s")
            finally:
                child.release()

    return asyncio.run(main())


def test_a_line_of_five_mebibytes_is_read_whole() -> None:
    line = _first_line(5 * 1024 * 1024, LIMIT)
    assert line == b"x" * (5 * 1024 * 1024) + b"\n"


def test_a_line_over_the_maximum_is_an_error_naming_the_maximum() -> None:
    with pytest.raises(LineTooLongError) as caught:
        _first_line(2 * 1024 * 1024, 1024 * 1024)
    assert caught.value.limit == 1024 * 1024
    assert "1048576" in str(caught.value)


# Requirement: Waiting for a child ends once it has exited, whatever output was left unread


async def _until_stdout_pauses(child: processes.ChildProcess) -> None:
    """Wait, within WAIT_LIMIT, until asyncio has stopped reading the child's standard output
    because its stream holds more than twice its limit unread."""
    transport = child._process._transport  # type: ignore[attr-defined]
    pipe = transport.get_pipe_transport(1)
    deadline = time.monotonic() + WAIT_LIMIT
    while pipe.is_reading():
        if time.monotonic() > deadline:
            pytest.fail(f"the child's output didn't pause within {WAIT_LIMIT:g}s")
        await asyncio.sleep(0.02)


def test_waiting_for_a_killed_child_whose_over_long_line_was_refused_ends() -> None:
    size, limit = 2 * 1024 * 1024, 1024 * 1024
    code = (
        f"import sys, time; sys.stdout.buffer.write(b'x' * {size} + b'\\n'); "
        "sys.stdout.flush(); time.sleep(60)"
    )

    async def main() -> tuple[int, bool, bytes]:
        child = await processes.start(_python(code), cwd=Path.cwd(), env={}, line_limit=limit)
        try:
            # The whole line arrives before it's read, so asyncio has paused the pipe (#187).
            await _until_stdout_pauses(child)
            with pytest.raises(LineTooLongError):
                await processes.read_line(child.stdout, limit)
            child.kill_tree()
            try:
                exit_code = await asyncio.wait_for(child.wait(), timeout=WAIT_LIMIT)
            except TimeoutError:
                pytest.fail(
                    f"waiting for the killed child took over {WAIT_LIMIT:g}s: its output was "
                    "left paused at the refused line, so its end was never read"
                )
            rest = await asyncio.wait_for(child.stdout.read(), timeout=WAIT_LIMIT)
            return exit_code, child.ended_by_kill(exit_code), rest
        finally:
            child.kill_tree()
            child.release()

    exit_code, by_kill, rest = asyncio.run(main())
    assert by_kill, f"exit code {exit_code} isn't the kill's"
    assert rest == b"x" * size + b"\n", f"{len(rest)} bytes of the {size + 1} the child wrote"


def test_reading_at_end_of_output_returns_the_unterminated_last_line_then_nothing() -> None:
    async def main() -> list[bytes]:
        child = await processes.start(
            _python("import sys; sys.stdout.buffer.write(b'a\\nlast')"),
            cwd=Path.cwd(),
            env={},
            line_limit=LIMIT,
        )
        lines = [await processes.read_line(child.stdout, LIMIT) for _ in range(3)]
        await child.wait()
        child.release()
        return lines

    assert asyncio.run(main()) == [b"a\n", b"last", b""]


# Requirement: A command can be run to completion within a bound


def _run(code: str, **overrides: object) -> processes.Completed:
    options: dict[str, object] = {
        "cwd": Path.cwd(),
        "env": {},
        "timeout": 30.0,
        "max_output_bytes": LIMIT,
        "announce_after": 30.0,
    }
    options.update(overrides)
    return processes.run_to_completion(_python(code), **options)  # type: ignore[arg-type]


def test_a_finished_command_returns_both_outputs_and_its_exit_code() -> None:
    done = _run("import sys; sys.stdout.write('out'); sys.stderr.write('err'); sys.exit(3)")
    assert (done.returncode, done.stdout, done.stderr) == (3, b"out", b"err")


def test_input_is_given_to_the_command_on_standard_input() -> None:
    done = _run("import sys; sys.stdout.write(sys.stdin.read().upper())", input=b"abc")
    assert done.stdout == b"ABC"


GRANDPARENT_THAT_TALKS = """
import subprocess, sys, time
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(grandchild.pid, flush=True)
time.sleep(120)
"""


def test_a_command_past_its_timeout_is_killed_with_its_children_and_keeps_its_output() -> None:
    with pytest.raises(ProcessTimeoutError) as caught:
        _run(GRANDPARENT_THAT_TALKS, timeout=3.0)
    error = caught.value
    assert error.timeout == 3.0
    assert error.command == sys.executable
    grandchild = int(error.stdout)
    assert _gone_within(grandchild, 10)


def test_a_command_whose_grandchild_starts_before_the_job_is_killed_with_it_at_its_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "grandchild.pid"
    monkeypatch.setattr(processes, "_before_job_assignment", _hold_the_job_assignment_open(marker))

    with pytest.raises(ProcessTimeoutError) as caught:
        _run(_early_grandparent(marker), timeout=3.0)

    assert caught.value.timeout == 3.0
    grandchild = int(marker.read_text())
    gone = _gone_within(grandchild, 10)
    _end_if_running(grandchild)
    assert gone, f"grandchild {grandchild} outlived the timeout's kill: it escaped the job"


def test_a_command_writing_past_the_output_limit_is_killed_and_the_limit_named() -> None:
    with pytest.raises(OutputTooLargeError) as caught:
        _run(
            "import sys, time\nwhile True: sys.stdout.write('x' * 65536)", max_output_bytes=100_000
        )
    assert caught.value.limit == 100_000
    assert "100000" in str(caught.value)


def test_a_command_run_from_inside_a_running_event_loop_completes_the_same_way() -> None:
    async def inside_a_loop() -> processes.Completed:
        return _run("print('from a loop')")

    assert asyncio.run(inside_a_loop()).stdout.strip() == b"from a loop"


def test_a_long_wait_is_announced_once_with_the_command_and_the_time_waited() -> None:
    waits: list[tuple[str, float]] = []
    _run(
        "import time; time.sleep(0.5)",
        announce_after=0.1,
        on_wait=lambda command, waited: waits.append((command, waited)),
    )
    assert len(waits) == 1
    assert waits[0][0] == sys.executable
    assert waits[0][1] >= 0.1


def test_a_command_that_exits_while_its_child_holds_its_output_open_still_times_out() -> None:
    code = (
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])"
    )
    with pytest.raises(ProcessTimeoutError):
        _run(code, timeout=2.0)


def test_running_a_missing_command_names_it() -> None:
    with pytest.raises(CommandNotFoundError):
        processes.run_to_completion(
            ["troupe-no-such-command"],
            cwd=Path.cwd(),
            env={},
            timeout=5,
            max_output_bytes=1024,
            announce_after=5,
        )


# Requirement: Whether a process has ended has one meaning on every platform

SLEEP_A_MINUTE = "import time; time.sleep(60)"


def _ended_by_kill(child: "subprocess.Popen[bytes]") -> None:
    child.kill()
    child.wait(timeout=30)


def test_a_live_child_reads_as_running() -> None:
    child = subprocess.Popen(_python(SLEEP_A_MINUTE))
    try:
        assert processes.is_running(child.pid)
    finally:
        _ended_by_kill(child)


def test_a_child_that_has_exited_and_been_waited_for_reads_as_ended() -> None:
    child = subprocess.Popen(_python("pass"))
    child.wait(timeout=30)
    assert not processes.is_running(child.pid)


STILL_ACTIVE = 259
"""The exit code Windows reports for a running process. A process can also exit with it."""

SYSTEM_PID = 4
"""The Windows System process: always running, and protected from most callers."""


@pytest.mark.skipif(not WINDOWS, reason="pid 4 is the System process only on Windows")
def test_the_windows_system_process_reads_as_running() -> None:
    assert processes.is_running(SYSTEM_PID)


DENY_EVERYONE_THEN_SLEEP = """
import ctypes, os, sys, time
from ctypes import wintypes
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
advapi32.SetSecurityInfo.restype = wintypes.DWORD
handle_kind_info = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD]
advapi32.SetSecurityInfo.argtypes = handle_kind_info + [ctypes.c_void_p] * 4
acl = ctypes.create_string_buffer(64)
if not advapi32.InitializeAcl(acl, 64, 2):  # ACL_REVISION: an ACL with no entries denies everyone
    sys.exit(f"InitializeAcl failed: {ctypes.get_last_error()}")
error = advapi32.SetSecurityInfo(
    kernel32.GetCurrentProcess(), 6, 4, None, None, acl, None  # kernel object, its DACL
)
if error:
    sys.exit(f"SetSecurityInfo failed: {error}")
print("denied", os.getpid(), flush=True)
time.sleep(60)
"""
"""A child that gives its own process an empty DACL, so opening it is refused to everyone not
holding an enabled SeDebugPrivilege, administrators included. It prints its own pid, because a
venv's python.exe on Windows is a launcher that runs the interpreter as a child of its own."""


ASK_WITHOUT_DEBUG_PRIVILEGE = """
import ctypes, json, sys
from ctypes import wintypes
pid = int(sys.argv[1])
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
token_out = ctypes.POINTER(wintypes.HANDLE)
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, token_out]

class Luid(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

class Privilege(ctypes.Structure):
    _fields_ = [("Luid", Luid), ("Attributes", wintypes.DWORD)]

class Privileges(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", Privilege * 1)]

token = wintypes.HANDLE()
if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x28, ctypes.byref(token)):
    sys.exit(f"OpenProcessToken failed: {ctypes.get_last_error()}")  # 0x28: adjust and query
luid = Luid()
if not advapi32.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
    sys.exit(f"LookupPrivilegeValueW failed: {ctypes.get_last_error()}")
remove = Privileges(1)
remove.Privileges[0].Luid = luid
remove.Privileges[0].Attributes = 0x4  # SE_PRIVILEGE_REMOVED
if not advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(remove), 0, None, None):
    sys.exit(f"AdjustTokenPrivileges failed: {ctypes.get_last_error()}")
handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
open_error = 0 if handle else ctypes.get_last_error()
if handle:
    kernel32.CloseHandle(handle)

from troupe.platform import processes

print(json.dumps({"open_error": open_error, "running": processes.is_running(pid)}))
"""
"""Asks about a pid from a process that has given up SeDebugPrivilege, which lets an administrator
open any process whatever its DACL. Prints the error opening it (0 if it opened) and the answer."""


@pytest.mark.skipif(not WINDOWS, reason="a process's DACL is Windows' own")
def test_a_windows_process_that_refuses_to_be_opened_reads_as_running() -> None:
    child = subprocess.Popen(_python(DENY_EVERYONE_THEN_SLEEP), stdout=subprocess.PIPE)
    try:
        assert child.stdout is not None
        said, pid = child.stdout.readline().split()
        assert said == b"denied"
        asked = subprocess.run(
            [*_python(ASK_WITHOUT_DEBUG_PRIVILEGE), pid.decode()],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert asked.returncode == 0, asked.stderr
        answer = json.loads(asked.stdout)
        # The refusal this test is about. If it didn't happen, say what the test process holds.
        assert answer["open_error"] == 5, (  # ERROR_ACCESS_DENIED
            f"opening process {pid.decode()} gave error {answer['open_error']}, not access denied; "
            f"privileges:\n{_privileges()}"
        )
        assert answer["running"] is True
    finally:
        _ended_by_kill(child)


def _privileges() -> str:
    whoami = shutil.which("whoami")
    if whoami is None:
        return "whoami not found"
    return subprocess.run(
        [whoami, "/priv"], capture_output=True, text=True, check=False
    ).stdout.strip()


def test_a_child_that_exited_with_the_still_active_code_reads_as_ended() -> None:
    """Held open by its parent on Windows, where the code is ambiguous; waited for elsewhere."""
    child = subprocess.Popen(_python(f"import sys; sys.exit({STILL_ACTIVE})"))
    if WINDOWS:
        _wait_until_exited_while_held(child)
        assert not processes.is_running(child.pid)
        assert child.wait(timeout=30) == STILL_ACTIVE
    else:
        child.wait(timeout=30)
        assert not processes.is_running(child.pid)


def _wait_until_exited_while_held(child: "subprocess.Popen[bytes]") -> None:
    """Wait for the child to exit while ``child`` keeps its handle open.

    ``Popen.poll`` reads the exit code through the handle it keeps, and can't tell 259 from
    "still running" either, so this waits on the handle with ``Popen.wait``'s own primitive.
    """
    if sys.platform != "win32":
        raise AssertionError("only Windows holds a handle to an exited child")
    import _winapi

    handle = child._handle  # type: ignore[attr-defined,unused-ignore]  # Popen's own
    assert _winapi.WaitForSingleObject(handle, 30_000) == _winapi.WAIT_OBJECT_0


def _may_signal_pid_1() -> bool:
    """Whether the OS lets us signal pid 1: as root, or in a container whose init runs as us."""
    try:
        os.kill(1, 0)
    except PermissionError:
        return False
    return True


@pytest.mark.skipif(WINDOWS, reason="pid 1 is init only on Linux and macOS")
@pytest.mark.skipif(
    not WINDOWS and _may_signal_pid_1(),
    reason="we may signal pid 1 here (root, or a container's init running as us), so the OS's "
    "refusal, which this test is about, never happens",
)
def test_pid_1_which_the_os_refuses_to_let_us_signal_reads_as_running() -> None:
    with pytest.raises(PermissionError):
        os.kill(1, 0)  # the refusal this test depends on
    assert processes.is_running(1)


@pytest.mark.skipif(WINDOWS, reason="a zombie is a Linux and macOS state")
def test_an_unreaped_child_still_reads_as_running_on_posix_the_documented_limit() -> None:
    child = subprocess.Popen(_python("pass"))
    try:
        _wait_until_zombie(child.pid)
        assert processes.is_running(child.pid)
    finally:
        child.wait(timeout=30)


def _wait_until_zombie(pid: int) -> None:
    """Wait, without reaping, until ``ps`` shows the child as a zombie (state ``Z``)."""
    ps = shutil.which("ps")
    assert ps is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = subprocess.run(
            [ps, "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
        ).stdout.strip()
        if state.startswith("Z"):
            return
        time.sleep(0.05)
    raise AssertionError(f"process {pid} didn't become a zombie within 10s")


def test_the_unknown_state_error_names_the_pid_the_os_text_and_the_code() -> None:
    error = ProcessStateUnknownError(4321, 22, "Invalid argument")
    assert str(error) == "can't tell whether process 4321 has ended: Invalid argument (error 22)"
    assert (error.pid, error.code, error.text) == (4321, 22, "Invalid argument")


def _os_error(code: int) -> OSError:
    return OSError(code, os.strerror(code))


@pytest.mark.parametrize(
    ("error", "running"),
    [(None, True), (_os_error(errno.EPERM), True), (_os_error(errno.ESRCH), False)],
    ids=["signalled", "refused", "no-such-process"],
)
def test_the_posix_table_reads_success_and_refusal_as_running_and_no_such_process_as_ended(
    error: OSError | None, running: bool
) -> None:
    assert processes._posix_outcome(1234, error) is running


@given(
    st.integers(min_value=1, max_value=4096).filter(lambda c: c not in {errno.EPERM, errno.ESRCH})
)
def test_any_other_posix_error_is_an_unknown_state_naming_the_pid_and_the_code(code: int) -> None:
    with pytest.raises(ProcessStateUnknownError) as caught:
        processes._posix_outcome(1234, OSError(code, "some failure"))
    assert (caught.value.pid, caught.value.code, caught.value.text) == (1234, code, "some failure")


@pytest.mark.parametrize(
    ("open_error", "wait_result", "running"),
    [
        (87, None, False),  # ERROR_INVALID_PARAMETER: no such process
        (5, None, True),  # ERROR_ACCESS_DENIED: it exists
        (None, 0x0, False),  # WAIT_OBJECT_0: the handle is signalled, it has exited
        (None, 0x102, True),  # WAIT_TIMEOUT: not signalled, still running
    ],
    ids=["no-such-process", "access-denied", "signalled", "not-signalled"],
)
def test_the_windows_table_reads_each_known_answer(
    open_error: int | None, wait_result: int | None, running: bool
) -> None:
    outcome = processes._windows_outcome(
        1234, open_error=open_error, wait_result=wait_result, wait_error=None
    )
    assert outcome is running


@given(st.integers(min_value=0, max_value=0xFFFFFFFF).filter(lambda c: c not in {5, 87}))
@example(2**31)  # FormatError takes a C long: found by this property on Windows CI
def test_any_other_windows_open_error_is_an_unknown_state_naming_the_pid_and_the_code(
    code: int,
) -> None:
    with pytest.raises(ProcessStateUnknownError) as caught:
        processes._windows_outcome(1234, open_error=code, wait_result=None, wait_error=None)
    assert (caught.value.pid, caught.value.code) == (1234, code)


def test_a_failed_windows_wait_is_an_unknown_state_carrying_the_wait_error() -> None:
    with pytest.raises(ProcessStateUnknownError) as caught:
        processes._windows_outcome(1234, open_error=None, wait_result=0xFFFFFFFF, wait_error=6)
    assert (caught.value.pid, caught.value.code) == (1234, 6)
    assert caught.value.text.startswith("waiting on the process failed: ")


@given(
    st.integers(min_value=0, max_value=0xFFFFFFFF).filter(
        lambda r: r not in {0x0, 0x102, 0xFFFFFFFF}
    )
)
def test_any_other_windows_wait_result_is_an_unknown_state_naming_it(result: int) -> None:
    with pytest.raises(ProcessStateUnknownError) as caught:
        processes._windows_outcome(1234, open_error=None, wait_result=result, wait_error=None)
    assert caught.value.pid == 1234
    assert caught.value.text == f"waiting on the process returned {result!r}"


NOT_A_PID = [0, -1, processes.PID_MAX + 1, True]


@pytest.fixture
def no_os_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if is_running reaches the OS."""

    def reached(*_: object) -> typing.NoReturn:
        raise AssertionError("is_running asked the OS about a value that isn't a pid")

    if sys.platform == "win32":
        monkeypatch.setattr(processes._kernel32, "OpenProcess", reached)
    else:
        monkeypatch.setattr(os, "kill", reached)


@pytest.mark.usefixtures("no_os_query")
@pytest.mark.parametrize("value", NOT_A_PID, ids=repr)
def test_a_value_that_cant_name_one_process_is_refused_naming_it_without_asking_the_os(
    value: int,
) -> None:
    with pytest.raises(ValueError, match=re.escape(f"{value!r} isn't a process id")):
        processes.is_running(value)


@pytest.mark.skipif(WINDOWS, reason="kill(pid, 0) is how Linux and macOS ask")
def test_an_os_error_that_isnt_a_refusal_or_no_such_process_fails_naming_the_pid_and_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fails(pid: int, signal: int) -> None:
        raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))

    monkeypatch.setattr(os, "kill", fails)
    with pytest.raises(ProcessStateUnknownError) as caught:
        processes.is_running(1234)
    assert (caught.value.pid, caught.value.code) == (1234, errno.EINVAL)
    assert str(caught.value).startswith("can't tell whether process 1234 has ended: ")
