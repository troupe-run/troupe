"""Hunt flaky tests: repeat them in overlapping rounds, optionally under load (spec: flake-hunt).

Usage: uv run scripts/flake_hunt.py [--workers N] [--rounds N] [--load N] [--round-timeout SECONDS]
                                    [--out DIR] [-k EXPRESSION] [PATH ...]

Each worker runs its rounds back to back, so the workers' rounds overlap. A round is one pytest
process over the selection (the whole suite when none is given), with a private hypothesis database,
so every round explores new examples and the repository's .hypothesis/ is never touched. Each round
is printed as it ends; the summary names every failing test with its runs, its failures and the
first failure's traceback. docs/flake-hunt.md says how to run it on each platform, and what to put
on #100 for a finding.

The hunt doesn't import troupe: it must still run, and report, when the code it hunts in is broken.
"""

import argparse
import collections
import contextlib
import dataclasses
import datetime
import json
import os
import platform
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parent.parent

POLL_SECONDS = 0.1
"""How often a worker looks at its round: has it ended, passed its timeout, or been stopped."""
JOIN_SECONDS = 0.5
"""The longest single wait on a worker: Windows can't interrupt a join with no timeout (D5)."""
STOP_ANNOUNCE_SECONDS = 2.0
STOP_TIMEOUT_SECONDS = 30.0
"""How long a stop waits for the workers before giving up on them, announcing the wait first."""
TAIL_CHARACTERS = 4000
"""How much of a crashed round's output the summary shows."""
LOAD_PROGRAM = "while True: pass"


class HuntError(Exception):
    """Something the hunt can't do, with what went wrong and the fix."""


def usable_cpus() -> int:
    """The CPUs this process may use: its affinity, or a container's limit, where Python sees it."""
    process_cpu_count: Callable[[], int | None] | None = getattr(os, "process_cpu_count", None)
    if process_cpu_count is not None:  # Python 3.13
        counted = process_cpu_count()
        if counted:
            return counted
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


# Options


@dataclasses.dataclass(frozen=True)
class Options:
    workers: int
    rounds: int
    load: int
    round_timeout: float
    out: Path
    root: Path
    keyword: str | None
    paths: tuple[str, ...]


def _whole(name: str, minimum: int) -> Callable[[str], int]:
    def parse(text: str) -> int:
        try:
            value = int(text, 10)
        except ValueError:
            value = None
        if value is None or value < minimum:
            raise argparse.ArgumentTypeError(
                f"{text!r} isn't allowed: {name} must be a whole number, {minimum} or more"
            )
        return value

    return parse


def _seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = None
    if value is None or not value > 0 or value == float("inf"):
        raise argparse.ArgumentTypeError(
            f"{text!r} isn't allowed: the round timeout must be a number of seconds above 0"
        )
    return value


def _default_out() -> Path:
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(tempfile.gettempdir()) / "flake-hunt" / stamp


def parse_options(argv: Sequence[str]) -> Options:
    parser = argparse.ArgumentParser(
        prog="flake_hunt.py",
        description="Repeat tests in overlapping rounds to find flaky ones (docs/flake-hunt.md).",
    )
    parser.add_argument(
        "--workers", type=_whole("--workers", 1), default=1, help="rounds run at once"
    )
    parser.add_argument(
        "--rounds", type=_whole("--rounds", 1), default=1, help="rounds each worker runs"
    )
    parser.add_argument(
        "--load", type=_whole("--load", 0), default=0, help="CPUs to keep busy while it runs"
    )
    parser.add_argument(
        "--round-timeout",
        type=_seconds,
        default=1200.0,
        metavar="SECONDS",
        help="a round running longer is stopped and reported as hung (default: 1200)",
    )
    parser.add_argument(
        "--out", type=Path, help="where results go (default: a new directory under the temp dir)"
    )
    parser.add_argument(
        "--root", type=Path, default=ROOT, help="where pytest runs (default: this repository)"
    )
    parser.add_argument("-k", dest="keyword", metavar="EXPRESSION", help="passed to pytest's -k")
    parser.add_argument("paths", nargs="*", help="test paths or ids (default: the whole suite)")
    parsed = parser.parse_args(argv)
    cpus = usable_cpus()
    if parsed.load > cpus:
        parser.error(
            f"argument --load: {parsed.load} isn't allowed: this machine lets the hunt use "
            f"{cpus} CPUs, and the load can be at most that"
        )
    root = parsed.root.resolve()
    if not root.is_dir():
        parser.error(f"argument --root: {str(parsed.root)!r} isn't a directory")
    for path in parsed.paths:
        if not (root / path.split("::", 1)[0]).exists():
            parser.error(f"{path!r} doesn't exist under {root}: name a test file or directory")
    return Options(
        workers=parsed.workers,
        rounds=parsed.rounds,
        load=parsed.load,
        round_timeout=parsed.round_timeout,
        out=(parsed.out or _default_out()).resolve(),
        root=root,
        keyword=parsed.keyword,
        paths=tuple(parsed.paths),
    )


# Process trees (design D4): everything a round or a load process starts is stopped with it.


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")

    _CREATE_SUSPENDED = 0x00000004
    _CREATE_NEW_PROCESS_GROUP = 0x00000200
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_SUSPEND_RESUME = 0x0800
    _STOPPED_EXIT_CODE = 1

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

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [  # the layout of JOBOBJECT_EXTENDED_LIMIT_INFORMATION
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", ctypes.c_uint64 * 6),  # IO_COUNTERS
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
    _ntdll.NtResumeProcess.restype = ctypes.c_long  # NTSTATUS
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

    def _windows_error(doing: str) -> HuntError:
        code = ctypes.get_last_error()
        return HuntError(
            f"couldn't {doing}: {ctypes.FormatError(code).strip()} (Windows error {code}). "
            "The hunt won't run rounds it can't stop; report this on #100"
        )

    def _new_job() -> int:
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            raise _windows_error("create a job object for a round")
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = _windows_error("make a round's job kill its processes when it closes")
            _kernel32.CloseHandle(job)
            raise error
        return int(job)

    def _assign_and_resume(job: int, pid: int) -> None:
        """Put a suspended process in the job, then let it run: nothing it starts escapes it."""
        process = _kernel32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE | _PROCESS_SUSPEND_RESUME, False, pid
        )
        if not process:
            raise _windows_error(f"open process {pid} to put it in its round's job")
        try:
            if not _kernel32.AssignProcessToJobObject(job, process):
                raise _windows_error(f"put process {pid} in its round's job")
            status = _ntdll.NtResumeProcess(process)
            if status != 0:
                raise HuntError(
                    f"couldn't resume process {pid} after putting it in its round's job "
                    f"(NTSTATUS {status & 0xFFFFFFFF:#010x}); report this on #100"
                )
        finally:
            _kernel32.CloseHandle(process)


class Tree:
    """A process started so that it and everything it starts can be stopped together."""

    def __init__(
        self, argv: Sequence[str], *, cwd: Path, env: dict[str, str], output: IO[bytes]
    ) -> None:
        self._job: int | None = None
        if sys.platform == "win32":
            self._job = _new_job()
            try:
                self.process = subprocess.Popen(
                    list(argv),
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    creationflags=_CREATE_SUSPENDED | _CREATE_NEW_PROCESS_GROUP,
                )
            except BaseException:
                _kernel32.CloseHandle(self._job)
                raise
            try:
                _assign_and_resume(self._job, self.process.pid)
            except BaseException:
                self.process.kill()
                self.process.wait()
                _kernel32.CloseHandle(self._job)
                raise
        else:
            self.process = subprocess.Popen(
                list(argv),
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    @property
    def pid(self) -> int:
        return self.process.pid

    def exited(self) -> bool:
        return self.process.poll() is not None

    def stop(self) -> int:
        """Stop the process and everything it started, and return its exit code.

        On POSIX the group is killed even when its leader has exited and been reaped: a group's id
        can't be reused while any process is still in the group, and once none is, there is
        nothing left to kill (``ESRCH``)."""
        if sys.platform == "win32":
            if self._job is not None:
                _kernel32.TerminateJobObject(self._job, _STOPPED_EXIT_CODE)
                code = self.process.wait()
                _kernel32.CloseHandle(self._job)  # the last handle: anything left dies with it
                self._job = None
                return code
            return self.process.wait()
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self.pid, signal.SIGKILL)
        return self.process.wait()


class _Running:
    """The trees running now, so a stop can reach every one of them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._trees: set[Tree] = set()

    @contextlib.contextmanager
    def holding(self, tree: Tree) -> Iterator[Tree]:
        with self._lock:
            self._trees.add(tree)
        try:
            yield tree
        finally:
            with self._lock:
                self._trees.discard(tree)

    def stop_all(self) -> None:
        with self._lock:
            trees = list(self._trees)
        for tree in trees:
            tree.stop()


# One round


@dataclasses.dataclass(frozen=True)
class Failure:
    test: str
    kind: str  # "failure" or "error"
    message: str
    traceback: str


@dataclasses.dataclass(frozen=True)
class Round:
    tag: str
    worker: int
    index: int
    status: str  # "passed", "failed", "crashed" (no report) or "hung"
    exit_code: int
    seconds: float
    tests: tuple[str, ...]
    failures: tuple[Failure, ...]
    output_tail: str  # the end of the output, for a round that crashed or hung

    @property
    def failed(self) -> bool:
        return self.status != "passed"

    def record(self) -> dict[str, Any]:
        return {
            "round": self.tag,
            "worker": self.worker,
            "index": self.index,
            "status": self.status,
            "exitCode": self.exit_code,
            "seconds": self.seconds,
            "tests": len(self.tests),
            "failures": [dataclasses.asdict(each) for each in self.failures],
            "outputTail": self.output_tail,
        }


def decode(data: bytes) -> str:
    """Bytes from a round, as text that can always be shown: what isn't UTF-8 is escaped."""
    return data.decode("utf-8", errors="backslashreplace")


def tail(path: Path) -> str:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return ""
    return decode(data)[-TAIL_CHARACTERS:]


def test_id(case: ET.Element) -> str:
    """A test's pytest id from its JUnit entry (xunit1, which records the file)."""
    name = case.get("name", "")
    file = (case.get("file") or "").replace("\\", "/")
    classname = case.get("classname", "")
    if not file:
        return f"{classname}::{name}"
    module = file.removesuffix(".py").replace("/", ".")
    inner = classname[len(module) + 1 :] if classname.startswith(module + ".") else ""
    return "::".join(part for part in (file, *inner.split("."), name) if part)


def read_report(path: Path) -> tuple[tuple[str, ...], tuple[Failure, ...]] | None:
    """Every test a round ran and every failure it reported, or None if there is no report."""
    try:
        tree = ET.parse(path)  # noqa: S314 - pytest's own report, written by this hunt's round
    except (FileNotFoundError, ET.ParseError):
        return None
    tests: list[str] = []
    failures: list[Failure] = []
    for case in tree.iter("testcase"):
        identity = test_id(case)
        tests.append(identity)
        for kind in ("failure", "error"):
            for element in case.findall(kind):
                failures.append(
                    Failure(identity, kind, element.get("message") or "", element.text or "")
                )
    return tuple(tests), tuple(failures)


def round_command(options: Options, basetemp: Path, report: Path) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--basetemp={basetemp}",
        f"--junitxml={report}",
        "-o",
        "junit_family=xunit1",
    ]
    if options.keyword is not None:
        command += ["-k", options.keyword]
    return command + list(options.paths)


def round_environment(options: Options, tag: str) -> dict[str, str]:
    """The hunt's own environment, unchanged except for the round's private hypothesis database
    (design D3, D10): anything else would make the round unlike a CI run."""
    env = dict(os.environ)
    env["HYPOTHESIS_STORAGE_DIRECTORY"] = str(options.out / "hypothesis" / tag)
    return env


def run_round(
    options: Options,
    temp_root: Path,
    worker: int,
    index: int,
    stop: threading.Event,
    running: _Running,
) -> Round | None:
    """Run one round to its end, its timeout or a stop. None when it was stopped part-way."""
    tag = f"w{worker}r{index}"
    report = options.out / "rounds" / f"{tag}.xml"
    log = options.out / "rounds" / f"{tag}.log"
    env = round_environment(options, tag)
    started = time.monotonic()
    hung = False
    with log.open("wb") as output:
        command = round_command(options, temp_root / tag, report)
        tree = Tree(command, cwd=options.root, env=env, output=output)
        with running.holding(tree):
            while not tree.exited():
                if stop.is_set():
                    tree.stop()
                    return None
                if time.monotonic() - started >= options.round_timeout:
                    hung = True
                    break
                time.sleep(POLL_SECONDS)
            exit_code = tree.stop()  # also stops anything the round left running
    seconds = round(time.monotonic() - started, 1)
    found = read_report(report)
    if hung:
        tests, failures = found or ((), ())
        return Round(tag, worker, index, "hung", exit_code, seconds, tests, failures, tail(log))
    if found is None:
        return Round(tag, worker, index, "crashed", exit_code, seconds, (), (), tail(log))
    tests, failures = found
    if failures:
        return Round(tag, worker, index, "failed", exit_code, seconds, tests, failures, "")
    if exit_code != 0:  # a report but no failure: no tests collected, an internal error, ...
        return Round(tag, worker, index, "crashed", exit_code, seconds, tests, (), tail(log))
    return Round(tag, worker, index, "passed", exit_code, seconds, tests, (), "")


def describe(each: Round) -> str:
    line = f"{each.tag} {each.status} in {each.seconds:g}s, {len(each.tests)} tests"
    if each.status == "crashed":
        line += f", exit code {each.exit_code} with no failure reported"
    if each.failures:
        line += ": " + ", ".join(sorted({failure.test for failure in each.failures}))
    return line


# The hunt


def load_average() -> list[float] | str:
    if hasattr(os, "getloadavg"):
        return [round(value, 2) for value in os.getloadavg()]
    return "not available"


@dataclasses.dataclass
class Hunt:
    options: Options
    rounds: list[Round] = dataclasses.field(default_factory=list)
    stopped: bool = False
    load_at_start: list[float] | str = "not available"
    load_at_end: list[float] | str = "not available"
    load_pids: list[int] = dataclasses.field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        runs: collections.Counter[str] = collections.Counter()
        failures: collections.Counter[str] = collections.Counter()
        first: dict[str, tuple[str, Failure]] = {}
        for each in sorted(self.rounds, key=lambda r: (r.index, r.worker)):
            runs.update(each.tests)
            for test in {failure.test for failure in each.failures}:
                failures[test] += 1
            for failure in each.failures:
                first.setdefault(failure.test, (each.tag, failure))
        options = self.options
        return {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "interpreter": sys.executable,
            "workers": options.workers,
            "rounds": options.rounds,
            "load": options.load,
            "roundTimeoutSeconds": options.round_timeout,
            "keyword": options.keyword,
            "paths": list(options.paths),
            "root": str(options.root),
            "loadAverageAtStart": self.load_at_start,
            "loadAverageAtEnd": self.load_at_end,
            "loadPids": self.load_pids,
            "stopped": self.stopped,
            "roundsRun": len(self.rounds),
            "roundsFailed": sum(each.failed for each in self.rounds),
            "tests": [
                {
                    "test": test,
                    "runs": runs[test],
                    "failures": failures[test],
                    "firstRound": first[test][0],
                    "message": first[test][1].message,
                    "traceback": first[test][1].traceback,
                }
                for test in sorted(failures, key=lambda t: (-failures[t], t))
            ],
            "roundsWithoutReport": [
                each.record() for each in self.rounds if each.status in ("crashed", "hung")
            ],
        }


def print_summary(summary: dict[str, Any], out: Path) -> None:
    load = summary["loadAverageAtEnd"]
    print()
    print(f"Platform: {summary['platform']}, Python {summary['python']} ({summary['interpreter']})")
    print(
        f"Workers {summary['workers']}, rounds {summary['rounds']} each, load {summary['load']}, "
        f"load average at the end: {load if isinstance(load, str) else ' '.join(map(str, load))}"
    )
    stopped = " (stopped part-way)" if summary["stopped"] else ""
    ran = summary["roundsRun"]
    print(f"{ran} round{'' if ran == 1 else 's'} ran{stopped}, {summary['roundsFailed']} failed.")
    for test in summary["tests"]:
        print()
        print(f"FAILED {test['test']}: {test['failures']} of {test['runs']} runs")
        print(f"  first in round {test['firstRound']}: {test['message']}")
        for line in test["traceback"].splitlines():
            print(f"    {line}")
    for each in summary["roundsWithoutReport"]:
        print()
        print(f"Round {each['round']} {each['status']} (exit code {each['exitCode']}). It ended:")
        for line in each["outputTail"].splitlines()[-40:]:
            print(f"    {line}")
    print()
    print(f"Results: {out}")


def _stop_workers(workers: list[threading.Thread]) -> None:
    started = time.monotonic()
    announced = False
    while any(worker.is_alive() for worker in workers):
        waited = time.monotonic() - started
        if waited >= STOP_TIMEOUT_SECONDS:
            print(f"flake_hunt: workers still running after {waited:.0f}s; giving up on them")
            return
        if not announced and waited >= STOP_ANNOUNCE_SECONDS:
            announced = True
            print("flake_hunt: waiting for the running rounds to stop", flush=True)
        for worker in workers:
            worker.join(JOIN_SECONDS)


def _raise_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def hunt(options: Options) -> Hunt:
    """Run the hunt, printing each round as it ends. Ctrl-C stops it, keeping what finished."""
    options.out.mkdir(parents=True, exist_ok=True)
    (options.out / "rounds").mkdir(exist_ok=True)
    temp_root = _new_temp_root()
    results = options.out / "results.jsonl"
    results.touch()
    state = Hunt(options, load_at_start=load_average())
    stop = threading.Event()
    running = _Running()
    lock = threading.Lock()
    errors: list[BaseException] = []

    def worker(number: int) -> None:
        try:
            for index in range(options.rounds):
                if stop.is_set():
                    return
                done = run_round(options, temp_root, number, index, stop, running)
                if done is None:
                    return
                with lock:
                    state.rounds.append(done)
                    with results.open("a", encoding="utf-8") as file:
                        file.write(json.dumps(done.record(), ensure_ascii=False) + "\n")
                    print(describe(done), flush=True)
        except BaseException as error:  # reported by the main thread, which stops the rest
            errors.append(error)
            stop.set()

    previous_break: Any = None
    if sys.platform == "win32":  # Ctrl-Break is all a process in its own console group receives
        previous_break = signal.signal(signal.SIGBREAK, _raise_interrupt)
    load: list[Tree] = []
    workers = [
        threading.Thread(target=worker, args=(n,), daemon=True) for n in range(options.workers)
    ]
    try:
        with open(os.devnull, "wb") as devnull:
            for _ in range(options.load):
                load.append(
                    Tree(
                        [sys.executable, "-c", LOAD_PROGRAM],
                        cwd=options.root,
                        env=dict(os.environ),
                        output=devnull,
                    )
                )
        state.load_pids = [busy.pid for busy in load]
        (options.out / "load.json").write_text(
            json.dumps({"pids": state.load_pids}) + "\n", encoding="utf-8"
        )
        for each in workers:
            each.start()
        while any(each.is_alive() for each in workers):
            for each in workers:
                each.join(JOIN_SECONDS)
    except KeyboardInterrupt:
        state.stopped = True
        print("\nflake_hunt: stopping", flush=True)
        stop.set()
        running.stop_all()
        _stop_workers(workers)
    finally:
        stop.set()
        running.stop_all()
        for busy in load:
            busy.stop()
        if sys.platform == "win32" and previous_break is not None:
            signal.signal(signal.SIGBREAK, previous_break)
        shutil.rmtree(temp_root, ignore_errors=True)
    state.load_at_end = load_average()
    if errors:
        raise errors[0]
    return state


def _new_temp_root() -> Path:
    """A short directory for the rounds' basetemps, so long paths don't change what the tests do."""
    base = Path(tempfile.gettempdir())
    while True:
        candidate = base / f"fh-{secrets.token_hex(3)}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a console's code page can't show every traceback
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    options = parse_options(sys.argv[1:] if argv is None else argv)
    print(
        f"flake_hunt: pid {os.getpid()}, {options.workers} workers x {options.rounds} rounds, "
        f"load {options.load}, Python {platform.python_version()} on {platform.platform()}",
        flush=True,
    )
    print(f"flake_hunt: results in {options.out}", flush=True)
    try:
        state = hunt(options)
    except HuntError as error:
        print(f"flake_hunt: {error}", file=sys.stderr)
        return 2
    summary = state.summary()
    (options.out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print_summary(summary, options.out)
    if state.stopped:
        return 130
    return 1 if summary["roundsFailed"] else 0


if __name__ == "__main__":
    sys.exit(main())
