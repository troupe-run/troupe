"""Claude Code's process: finding, starting and stopping it, and how it ended (design D6, D9).

The only module of the runner that imports ``signal`` or a Windows API, or branches on the
operating system: an import-linter contract keeps it so. The runner can't use troupe.platform,
because a plugin imports nothing from troupe.

Claude Code stays in the runner's process group on POSIX, so troupe's kill of the runner's group
reaches it too. On Windows it gets a job of its own, nested in the runner's, so stopping it ends
every process it started, a ``claude.cmd`` shim's ``node`` included.
"""

import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

WINDOWS = sys.platform == "win32"

_WINDOWS_STOPPED_EXIT_CODE = 1
"""The exit code a stopped Claude Code gets on Windows, where there is no signal to report."""


def find_claude(path: str | None) -> Path | None:
    """The ``claude`` program on ``path`` (a ``PATH`` value), or None when there's none.

    Only absolute entries are searched: an empty or relative entry would resolve against the
    working directory, which is the workspace, so a file there could stand in for Claude Code. On
    Windows each ``PATHEXT`` extension is tried, as the shell does.
    """
    if not path:
        return None
    names = ["claude"]
    if WINDOWS:
        extensions = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep)
        names = [f"claude{ext.lower()}" for ext in extensions if ext]
    for entry in path.split(os.pathsep):
        directory = Path(entry)
        if not entry or not directory.is_absolute():
            continue
        for name in names:
            candidate = directory / name
            if candidate.is_file() and (WINDOWS or os.access(candidate, os.X_OK)):
                return candidate
    return None


class Claude:
    """A running Claude Code, with its pipes."""

    def __init__(self, process: subprocess.Popen[bytes], job: int | None) -> None:
        self.process = process
        self._job = job

    @property
    def pid(self) -> int:
        return self.process.pid

    def poll(self) -> int | None:
        return self.process.poll()

    def wait(self, timeout: float | None = None) -> int | None:
        """The exit status, or None if ``timeout`` passed first."""
        try:
            return self.process.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def stop(self, grace: float) -> int:
        """Ask Claude Code to stop, kill it if it hasn't within ``grace`` seconds, and return its
        exit status once it has ended. On Windows the stop is a termination at once."""
        if (status := self.process.poll()) is not None:
            return status
        if WINDOWS:
            if self._job is not None:
                _terminate_job(self._job)
            else:
                self.process.terminate()
            return self.process.wait()
        self.process.send_signal(signal.SIGTERM)
        if (status := self.wait(grace)) is not None:
            return status
        self.process.kill()
        return self.process.wait()

    def release(self) -> None:
        """Let go of the job, once Claude Code has ended. Closing it kills anything left in it."""
        if self._job is not None:
            _close_job(self._job)
            self._job = None


def start(argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> Claude:
    """Start Claude Code with piped standard streams. Raises OSError when it can't be started."""
    process = subprocess.Popen(  # noqa: S603 - argv is built by command.py from checked options
        list(argv),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    job = None
    if WINDOWS:
        try:
            job = _new_job_for(process.pid)
        except OSError:
            # Assignment can fail if Claude Code has already exited; stop() falls back to
            # terminating the process, and troupe's own job still holds its children.
            job = None
    return Claude(process, job)


def exit_code(status: int) -> int:
    """The runner's exit code for Claude Code's exit status (design D7): 0 for 0, the status itself
    from 1 to 255, 128 + n for POSIX signal n, and 1 for anything else."""
    if 0 <= status <= 255:
        return status
    if -64 < status < 0:
        return 128 - status
    return 1


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100

    class _BasicLimits(ctypes.Structure):
        _fields_ = [  # the layout of JOBOBJECT_BASIC_LIMIT_INFORMATION
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [  # the layout of IO_COUNTERS
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [  # the layout of JOBOBJECT_EXTENDED_LIMIT_INFORMATION
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    def _check(ok: object) -> None:
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def _new_job_for(pid: int) -> int:
        job = _kernel32.CreateJobObjectW(None, None)
        _check(job)
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            _check(
                _kernel32.SetInformationJobObject(
                    job,
                    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                    ctypes.byref(limits),
                    ctypes.sizeof(limits),
                )
            )
            process = _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
            _check(process)
            try:
                _check(_kernel32.AssignProcessToJobObject(job, process))
            finally:
                _kernel32.CloseHandle(process)
        except OSError:
            _kernel32.CloseHandle(job)
            raise
        return int(job)

    def _terminate_job(job: int) -> None:
        _kernel32.TerminateJobObject(job, _WINDOWS_STOPPED_EXIT_CODE)

    def _close_job(job: int) -> None:
        _kernel32.CloseHandle(job)

else:

    def _new_job_for(pid: int) -> int:
        raise NotImplementedError("POSIX children stay in the runner's process group")

    def _terminate_job(job: int) -> None:
        raise NotImplementedError("POSIX children are stopped with signals")

    def _close_job(job: int) -> None:
        raise NotImplementedError("POSIX children have no job")


__all__ = ["WINDOWS", "Claude", "exit_code", "find_claude", "start"]
