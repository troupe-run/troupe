"""Tests for child processes (spec: platform).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_platform_processes.py."""

import asyncio
import errno
import os
import re
import sys
import time
import typing
from pathlib import Path

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from platform_processes_shared import LIMIT, WINDOWS
from troupe.platform import processes
from troupe.platform.errors import (
    CommandNotFoundError,
    ProcessStateUnknownError,
)


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


SYSTEM_PID = 4
"""The Windows System process: always running, and protected from most callers."""


@pytest.mark.skipif(not WINDOWS, reason="pid 4 is the System process only on Windows")
def test_the_windows_system_process_reads_as_running() -> None:
    assert processes.is_running(SYSTEM_PID)


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


def test_a_namespace_token_read_twice_is_the_same() -> None:
    first = processes.namespace_token()
    time.sleep(0.2)
    assert processes.namespace_token() == first


def test_the_namespace_token_holds_what_names_the_namespace_on_this_os() -> None:
    import socket

    token = processes.namespace_token()
    assert token is not None
    assert "\n" not in token
    if sys.platform == "linux":
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        assert boot_id in token
        assert os.readlink("/proc/self/ns/pid") in token
    else:
        assert socket.gethostname() in token


@pytest.mark.parametrize(
    "error",
    [OSError(errno.EACCES, "refused"), UnicodeDecodeError("ascii", b"\xff", 0, 1, "not ascii")],
    ids=["os-error", "undecodable"],
)
def test_a_namespace_the_os_cant_name_gives_no_token(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def failing() -> tuple[str, ...]:
        raise error

    monkeypatch.setattr(processes, "_namespace_parts", failing)
    assert processes.namespace_token() is None


@pytest.mark.parametrize(
    "parts", [(), ("linux", ""), ("linux", "a\nb")], ids=["none", "empty", "two-lines"]
)
def test_a_namespace_part_that_cant_be_one_line_gives_no_token(
    monkeypatch: pytest.MonkeyPatch, parts: tuple[str, ...]
) -> None:
    monkeypatch.setattr(processes, "_namespace_parts", lambda: parts)
    assert processes.namespace_token() is None
