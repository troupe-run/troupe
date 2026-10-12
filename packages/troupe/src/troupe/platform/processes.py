"""Child processes (spec: platform; runner-contract design D6).

A child starts in its own process group, with only the environment the caller names plus the
minimum the platform needs, so that it and every process it starts can be killed together.

Platform differences, handled here so callers see one behaviour:
- POSIX: the child starts a new session (and so a new process group); killing the tree sends
  SIGKILL to the group. A grandchild that starts its own session escapes the group: a documented
  limitation (docs/platform.md).
- Windows: the child starts in a new process group and is assigned at once to a new job object
  created with kill-on-close. Killing the tree terminates the job, and the tree also dies if troupe
  does, because the job's last handle closes with it. Windows needs ``SYSTEMROOT`` to start Python
  and use sockets, so it is always passed.
- Both: the command is resolved to an absolute path before starting, using the caller's search
  path, so the child doesn't need ``PATH`` itself.
"""

import asyncio
import contextlib
import os
import shutil
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from troupe.platform.errors import CommandNotFoundError, EnvironmentPolicyError, LineTooLongError

_WINDOWS = sys.platform == "win32"

MINIMUM_ENVIRONMENT: tuple[str, ...] = ("SYSTEMROOT",) if _WINDOWS else ()
"""The variables passed to every child, whatever the caller names, when the parent has them."""


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


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259

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
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
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

    def _kill_job(job: int) -> None:
        _kernel32.TerminateJobObject(job, 1)

    def _close_job(job: int) -> None:
        _kernel32.CloseHandle(job)

    def _kill_group(pid: int) -> None:
        raise NotImplementedError("Windows children are killed through their job")

    def is_running(pid: int) -> bool:
        """Whether a process with this id is running."""
        process = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            return False
        try:
            code = wintypes.DWORD()
            if not _kernel32.GetExitCodeProcess(process, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            _kernel32.CloseHandle(process)

else:
    import signal

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
        """Whether a process with this id is running (a zombie awaiting its parent counts)."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # it exists, owned by someone else
        return True


class ChildProcess:
    """A started child: its standard streams, waiting for it, and killing its whole tree."""

    def __init__(self, process: asyncio.subprocess.Process, job: int | None) -> None:
        self._process = process
        self._job = job
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
        if self._job is not None:
            _kill_job(self._job)
        else:
            _kill_group(self._process.pid)

    def release(self) -> None:
        """Let go of the platform resources held for the child. Call once it has exited.

        On Windows this closes the job, which kills any process of the tree still running.
        """
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
