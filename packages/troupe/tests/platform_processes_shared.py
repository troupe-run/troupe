"""What test_platform_processes.py and test_platform_processes_unit.py share."""

import contextlib
import os
import sys
import time
import typing
from collections.abc import Callable, Iterator

import pytest

WINDOWS = sys.platform == "win32"
LIMIT = 8 * 1024 * 1024

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
