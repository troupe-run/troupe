"""Child processes (spec: platform; runner-contract design D6).

A child starts in its own process group, with only the environment the caller names plus the
minimum the platform needs, so that it and every process it starts can be killed together.

Platform differences, handled here so callers see one behaviour:
- POSIX: the child starts a new session (and so a new process group); killing the tree sends
  SIGKILL to the group. A grandchild that starts its own session escapes the group: a documented
  limitation (contributing/platform.md).
- Windows: the child starts in a new process group and is assigned at once to a new job object
  created with kill-on-close. Killing the tree terminates the job with KILLED_EXIT_CODE, and the
  tree also dies if troupe does, because the job's last handle closes with it. Windows needs
  ``SYSTEMROOT`` to start Python and use sockets, so it is always passed.
- Both: the command is resolved to an absolute path before starting, using the caller's search
  path, so the child doesn't need ``PATH`` itself.
- Both: ``is_running`` answers one question, has the process ended? A process the OS refuses
  access to is running; one is ended only when the OS says there is no such process or that it
  has exited; anything else raises ProcessStateUnknownError rather than guessing. POSIX asks with
  ``kill(pid, 0)``, which can't see that an unreaped child (a zombie) has exited: a documented
  limitation (contributing/platform.md). Windows asks whether the process handle is signalled.
"""

import asyncio
import contextlib
import errno
import os
import shutil
import subprocess
import sys
import threading
import time
import typing
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from troupe.platform.errors import (
    CommandNotFoundError,
    EnvironmentPolicyError,
    LineTooLongError,
    OutputTooLargeError,
    ProcessStateUnknownError,
    ProcessTimeoutError,
)

_WINDOWS = sys.platform == "win32"

MINIMUM_ENVIRONMENT: tuple[str, ...] = ("SYSTEMROOT",) if _WINDOWS else ()
"""The variables passed to every child, whatever the caller names, when the parent has them."""

KILLED_EXIT_CODE = 0x74726B6C
"""The exit code a kill gives a Windows child: "trkl" in ASCII, 1953655660. Terminating a job
sets whatever code the caller names, so troupe names one no program commonly exits with and that
isn't an NTSTATUS crash code, to tell its kill apart from a child that exited by itself. On
Linux and macOS a kill is SIGKILL, which no exit code can be mistaken for."""


def _key(name: str) -> str:
    """Environment names are case-insensitive on Windows, case-sensitive elsewhere."""
    return name.upper() if _WINDOWS else name


@dataclass(frozen=True)
class EnvironmentPolicy:
    """Which of the parent's environment variables a kind of child may receive (design D6).

    Each port or adapter declares one, as a named default in one place. Nothing is inherited
    except what a policy selects: ``names`` exactly and ``prefixes`` by prefix, minus ``never``
    (exactly) and ``never_prefixes``. A policy can be narrowed, never widened.
    """

    names: frozenset[str] = frozenset()
    prefixes: tuple[str, ...] = ()
    never: frozenset[str] = frozenset()
    never_prefixes: tuple[str, ...] = ()

    def selects(self, name: str) -> bool:
        key = _key(name)
        return (
            key in {_key(n) for n in self.names}
            or any(key.startswith(_key(p)) for p in self.prefixes)
        ) and not self.forbids(name)

    def forbids(self, name: str) -> bool:
        key = _key(name)
        return key in {_key(n) for n in self.never} or any(
            key.startswith(_key(p)) for p in self.never_prefixes
        )

    def narrow(
        self,
        *,
        names: Iterable[str] | None = None,
        prefixes: Iterable[str] | None = None,
        never: Iterable[str] = (),
        never_prefixes: Iterable[str] = (),
    ) -> "EnvironmentPolicy":
        """A narrower policy: keep only ``names`` and ``prefixes`` (each already selected here),
        and pass ``never`` and ``never_prefixes`` in addition. Anything wider is refused."""
        kept_names = self.names if names is None else frozenset(names)
        kept_prefixes = self.prefixes if prefixes is None else tuple(prefixes)
        mine = {_key(n) for n in self.names}
        for name in kept_names:
            if _key(name) not in mine:
                raise EnvironmentPolicyError(
                    name, "narrowing can't select a name the policy doesn't select"
                )
        for prefix in kept_prefixes:
            if not any(_key(prefix).startswith(_key(p)) for p in self.prefixes):
                raise EnvironmentPolicyError(
                    prefix, "narrowing can't select a prefix the policy doesn't select"
                )
        return EnvironmentPolicy(
            names=kept_names,
            prefixes=kept_prefixes,
            never=self.never | frozenset(never),
            never_prefixes=self.never_prefixes + tuple(never_prefixes),
        )


def build_environment(
    policy: EnvironmentPolicy,
    *,
    source: Mapping[str, str] | None = None,
    explicit: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The environment for a child: the platform minimum, what ``policy`` selects from ``source``
    (the parent's environment when omitted), then ``explicit`` values.

    An explicit value for a name the policy never passes is refused, not dropped: the caller and
    the policy disagree, and guessing which one is right could leak or lose a variable.
    """
    parent = os.environ if source is None else source
    environment = {name: parent[name] for name in MINIMUM_ENVIRONMENT if name in parent}
    environment.update({name: value for name, value in parent.items() if policy.selects(name)})
    for name, value in (explicit or {}).items():
        if policy.forbids(name):
            raise EnvironmentPolicyError(name, "this policy never passes it")
        environment[name] = value
    return environment


PID_MAX = 2**31 - 1
"""The largest pid any supported platform can name (POSIX ``pid_t`` is a signed 32-bit integer)."""

_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87
_WAIT_OBJECT_0 = 0x0
_WAIT_TIMEOUT = 0x102
_WAIT_FAILED = 0xFFFFFFFF


def _check_pid(pid: int) -> None:
    """Refuse a value that can't name one process, before any OS call.

    On POSIX ``0`` and negative values address process groups, and on Windows ``0`` is the System
    Idle Process. A larger value would overflow ``pid_t``, or be truncated to another pid on
    Windows. A ``bool`` is an ``int`` to Python, but never a pid.
    """
    if isinstance(pid, bool) or not isinstance(pid, int) or not 0 < pid <= PID_MAX:
        raise ValueError(f"{pid!r} isn't a process id: a pid is an integer from 1 to {PID_MAX}")


def _posix_outcome(pid: int, error: OSError | None) -> bool:
    """Whether ``pid`` is running, from what ``kill(pid, 0)`` said.

    Success, or a refusal (``EPERM``), means it exists; ``ESRCH`` means it has ended. Anything else
    can't tell, and raises ProcessStateUnknownError.
    """
    if error is None or error.errno == errno.EPERM:
        return True
    if error.errno == errno.ESRCH:
        return False
    raise ProcessStateUnknownError(pid, error.errno, error.strerror or str(error))


def _windows_outcome(
    pid: int, *, open_error: int | None, wait_result: int | None, wait_error: int | None
) -> bool:
    """Whether ``pid`` is running, from what ``OpenProcess`` and ``WaitForSingleObject`` said.

    A failed open means ended for ``ERROR_INVALID_PARAMETER`` (no such process) and running for
    ``ERROR_ACCESS_DENIED`` (it exists). An opened process has ended exactly when its handle is
    signalled, which, unlike its exit code, has no value a process can also exit with. Anything
    else can't tell, and raises ProcessStateUnknownError.
    """
    if open_error is not None:
        if open_error == _ERROR_INVALID_PARAMETER:
            return False
        if open_error == _ERROR_ACCESS_DENIED:
            return True
        raise ProcessStateUnknownError(pid, open_error, _windows_error_text(open_error))
    if wait_result == _WAIT_OBJECT_0:
        return False
    if wait_result == _WAIT_TIMEOUT:
        return True
    if wait_result == _WAIT_FAILED:
        text = "waiting on the process failed"
        if wait_error is not None:
            text = f"{text}: {_windows_error_text(wait_error)}"
        raise ProcessStateUnknownError(pid, wait_error, text)
    raise ProcessStateUnknownError(pid, None, f"waiting on the process returned {wait_result!r}")


def _windows_error_text(code: int) -> str:
    """The OS's description of a Windows error code, where the OS can describe it."""
    if sys.platform == "win32":
        import ctypes

        # FormatError takes a C long; a Windows error code is a DWORD, so pass its bits signed.
        return ctypes.FormatError(ctypes.c_long(code).value).strip()
    return f"Windows error {code}"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _SYNCHRONIZE = 0x00100000

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
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
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
        return int(job)

    _KILL_STATUS = KILLED_EXIT_CODE

    def _kill_job(job: int) -> None:
        _kernel32.TerminateJobObject(job, KILLED_EXIT_CODE)

    def _close_job(job: int) -> None:
        _kernel32.CloseHandle(job)

    def _kill_group(pid: int) -> None:
        raise NotImplementedError("Windows children are killed through their job")

    def is_running(pid: int) -> bool:
        """Whether the process with this id hasn't ended (spec: platform).

        Read from whether its handle is signalled, not from its exit code, which a process can
        exit with 259 (``STILL_ACTIVE``) and so can't tell apart from running. A process the OS
        refuses to open exists, so it is running. Raises ProcessStateUnknownError when the OS
        can't say, and ValueError for a value that can't name one process.
        """
        _check_pid(pid)
        process = _kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid
        )
        if not process:
            return _windows_outcome(
                pid, open_error=ctypes.get_last_error(), wait_result=None, wait_error=None
            )
        try:
            result = _kernel32.WaitForSingleObject(process, 0)
            error = ctypes.get_last_error() if result == _WAIT_FAILED else None
        finally:
            _kernel32.CloseHandle(process)
        return _windows_outcome(pid, open_error=None, wait_result=result, wait_error=error)

else:
    import signal

    _KILL_STATUS = -signal.SIGKILL

    def _new_job_for(pid: int) -> int:
        raise NotImplementedError("job objects exist only on Windows")

    def _kill_job(job: int) -> None:
        raise NotImplementedError("job objects exist only on Windows")

    def _close_job(job: int) -> None:
        raise NotImplementedError("job objects exist only on Windows")

    def _kill_group(pid: int) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)

    def is_running(pid: int) -> bool:
        """Whether the process with this id hasn't ended (spec: platform).

        A process the OS refuses to let us signal exists, so it is running. One that has exited
        but hasn't been waited for by its parent (a zombie) still reads as running: a documented
        limit (contributing/platform.md). Raises ProcessStateUnknownError when the OS can't say, and
        ValueError for a value that can't name one process.
        """
        _check_pid(pid)
        try:
            os.kill(pid, 0)
        except OSError as error:
            return _posix_outcome(pid, error)
        return _posix_outcome(pid, None)


class ChildProcess:
    """A started child: its standard streams, waiting for it, and killing its whole tree."""

    def __init__(self, process: asyncio.subprocess.Process, job: int | None) -> None:
        self._process = process
        self._job = job
        self._kill_sent = False
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise RuntimeError("a child process must be started with all three streams piped")
        self.stdin: asyncio.StreamWriter = process.stdin
        self.stdout: asyncio.StreamReader = process.stdout
        self.stderr: asyncio.StreamReader = process.stderr

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    async def wait(self) -> int:
        """Wait for the child to exit and return its exit code."""
        return await self._process.wait()

    def close_stdin(self) -> None:
        """Close the child's standard input, so it reads end of file."""
        with contextlib.suppress(OSError, RuntimeError):
            self.stdin.close()

    def kill_tree(self) -> None:
        """Kill the child and every process it started. Safe to call more than once."""
        self._kill_sent = True
        if self._job is not None:
            _kill_job(self._job)
        else:
            _kill_group(self._process.pid)

    def ended_by_kill(self, exit_code: int) -> bool:
        """Whether troupe's kill is what ended the child, given the exit code ``wait()`` returned.

        True only when ``kill_tree()`` was called and the exit status is the one a kill gives. A
        child that exited by itself before the kill landed keeps its own code, so this is false
        for it, however the timing of the kill and of seeing the exit fell.
        """
        return self._kill_sent and exit_code == _KILL_STATUS

    def release(self) -> None:
        """Let go of the platform resources held for the child. Call once it has exited.

        On Windows this closes the job, which kills any process of the tree still running. On every
        platform it closes the child's pipes now, while the event loop is still running, rather
        than leaving them to be closed after the loop has gone.
        """
        self.close_stdin()
        # asyncio.subprocess.Process has no public close; its transport is the documented
        # SubprocessTransport, reached through the attribute asyncio itself uses.
        transport = getattr(self._process, "_transport", None)
        if isinstance(transport, asyncio.SubprocessTransport):
            transport.close()
        if self._job is not None:
            _close_job(self._job)
            self._job = None


def resolve_command(command: str, search_path: str | None) -> str:
    """The absolute path of ``command``, found on ``search_path`` when it has no directory part."""
    found = shutil.which(command, path=search_path)
    if found is None:
        raise CommandNotFoundError(command)
    return str(Path(found).absolute())


async def start(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str],
    env: Mapping[str, str],
    line_limit: int,
    search_path: str | None = None,
) -> ChildProcess:
    """Start ``argv`` in its own process group with only ``env`` plus the platform minimum.

    ``search_path`` is where the command is looked for (the parent's ``PATH`` when omitted).
    ``line_limit`` is the longest line ``read_line`` will accept from the child's output.
    """
    if not argv:
        raise CommandNotFoundError("")
    command = resolve_command(argv[0], search_path)
    child_env = {name: os.environ[name] for name in MINIMUM_ENVIRONMENT if name in os.environ}
    child_env.update(env)
    stdio = asyncio.subprocess.PIPE
    if sys.platform == "win32":
        process = await asyncio.create_subprocess_exec(
            command,
            *argv[1:],
            cwd=cwd,
            env=child_env,
            stdin=stdio,
            stdout=stdio,
            stderr=stdio,
            limit=line_limit,
            creationflags=0x00000200,  # CREATE_NEW_PROCESS_GROUP
        )
        try:
            job = _new_job_for(process.pid)
        except OSError:
            process.kill()
            await process.wait()
            raise
        return ChildProcess(process, job)
    process = await asyncio.create_subprocess_exec(
        command,
        *argv[1:],
        cwd=cwd,
        env=child_env,
        stdin=stdio,
        stdout=stdio,
        stderr=stdio,
        limit=line_limit,
        start_new_session=True,
    )
    return ChildProcess(process, None)


async def read_line(stream: asyncio.StreamReader, limit: int) -> bytes:
    """Read one line, including its line feed. Returns ``b""`` at end of file.

    A line longer than ``limit`` (the ``line_limit`` the child was started with) raises
    LineTooLongError rather than hanging or being cut short.
    """
    try:
        return await stream.readuntil(b"\n")
    except asyncio.IncompleteReadError as error:
        return error.partial  # end of file: the last line has no line feed, or there is none
    except asyncio.LimitOverrunError as error:
        raise LineTooLongError(limit) from error


ProcessWaitCallback = Callable[[str, float], None]
"""Called once when a command has run for ``announce_after`` seconds, with the command and time."""

_CREATE_NEW_PROCESS_GROUP = 0x00000200
_READ_CHUNK = 64 * 1024
_POLL_SECONDS = 0.02


@dataclass(frozen=True)
class Completed:
    """A command that ran to completion."""

    returncode: int
    stdout: bytes
    stderr: bytes


class _Output:
    """Both output streams of one command, drained by threads, with a shared size limit."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.total = 0
        self.overflowed = threading.Event()
        self._lock = threading.Lock()

    def drain(self, stream: "typing.IO[bytes]", into: bytearray) -> None:
        with contextlib.suppress(OSError, ValueError):
            while chunk := stream.read1(_READ_CHUNK):  # type: ignore[attr-defined]
                with self._lock:
                    into.extend(chunk)
                    self.total += len(chunk)
                    if self.total > self.limit:
                        self.overflowed.set()


def run_to_completion(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str],
    env: Mapping[str, str],
    timeout: float,
    max_output_bytes: int,
    announce_after: float,
    input: bytes | None = None,
    on_wait: ProcessWaitCallback | None = None,
    search_path: str | None = None,
) -> Completed:
    """Run a short command to completion, bounded (spec: platform; design D6).

    It blocks, and uses no event loop, so it works from anywhere, including inside a running loop
    (wrap it in ``asyncio.to_thread`` to keep the loop free). The command starts in its own process
    group (POSIX) or job object (Windows) with exactly ``env`` plus the platform minimum. Past
    ``timeout``, or past ``max_output_bytes`` of output in both streams together, the whole process
    tree is killed and ProcessTimeoutError or OutputTooLargeError is raised. A run longer than
    ``announce_after`` is announced once through ``on_wait``. A command that exits but leaves a
    process holding its output open counts as still running.
    """
    if not argv:
        raise CommandNotFoundError("")
    command = resolve_command(argv[0], search_path)
    child_env = {name: os.environ[name] for name in MINIMUM_ENVIRONMENT if name in os.environ}
    child_env.update(env)
    process = subprocess.Popen(  # noqa: S603 - argv is the caller's, resolved to an absolute path
        [command, *argv[1:]],
        cwd=cwd,
        env=child_env,
        stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=not _WINDOWS,
        creationflags=_CREATE_NEW_PROCESS_GROUP if _WINDOWS else 0,
    )
    job: int | None = None
    try:
        if _WINDOWS:
            job = _new_job_for(process.pid)
    except OSError:
        process.kill()
        process.wait()
        raise
    output = _Output(max_output_bytes)
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("the command's output must be piped")
    threads = [
        threading.Thread(target=output.drain, args=(process.stdout, output.stdout), daemon=True),
        threading.Thread(target=output.drain, args=(process.stderr, output.stderr), daemon=True),
    ]
    if input is not None and process.stdin is not None:
        threads.append(threading.Thread(target=_feed, args=(process.stdin, input), daemon=True))
    for thread in threads:
        thread.start()

    def kill() -> None:
        if job is not None:
            _kill_job(job)
        else:
            _kill_group(process.pid)
        process.wait()
        for thread in threads:
            thread.join(timeout=5)

    started = time.monotonic()
    announced = False
    try:
        while True:
            finished = process.poll() is not None and not any(t.is_alive() for t in threads[:2])
            if output.overflowed.is_set():
                kill()
                raise OutputTooLargeError(argv[0], max_output_bytes)
            if finished:
                break
            waited = time.monotonic() - started
            if waited >= timeout:
                kill()
                raise ProcessTimeoutError(
                    argv[0], timeout, bytes(output.stdout), bytes(output.stderr)
                )
            if not announced and waited >= announce_after:
                announced = True
                if on_wait is not None:
                    on_wait(argv[0], waited)
            time.sleep(_POLL_SECONDS)
    finally:
        if job is not None:
            _close_job(job)
    return Completed(process.returncode, bytes(output.stdout), bytes(output.stderr))


def _feed(stdin: "typing.IO[bytes]", data: bytes) -> None:
    with contextlib.suppress(OSError, ValueError):
        stdin.write(data)
    with contextlib.suppress(OSError, ValueError):
        stdin.close()
