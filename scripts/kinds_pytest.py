"""pytest plugin: every test is unit or integration by its directory, and a unit test stays inside
its process (spec: quality-check; test-split design D3a-D6).

Load it from the repository's pytest configuration, with scripts/ on pytest's pythonpath:

    addopts = ["-p", "kinds_pytest"]

Each suite (a `testpaths` entry) keeps its tests in `unit/` and `integration/`, and a test's
directory is its kind. Before `-m` selects, every test is tagged `unit` or `integration` from its
directory, so `-m unit` and `-m "not integration"` select the unit tests. A test file in neither
directory fails to collect, which stops the run; a test with a kind written by hand, or whose
module imports another test module, fails.

What makes a test integration is reaching outside its process, and the kinds of reach are declared
in `OUTSIDE`, the one place to change: a kind added there fails every unit test that uses it from
the next run on. Each kind names the Python audit events that are that reach. An audit hook records
them while each test, and each fixture, runs; a fixture's events count for every test that uses it,
even after an earlier test set it up. A unit test with anything recorded fails at teardown, naming
what it reached. An integration test that reached nothing passes: a test can reach outside on one
OS only.

The hook sees this process only: what a child process does isn't seen, but starting it is.
"""

from __future__ import annotations

import ast
import contextlib
import fnmatch
import os
import platform
import socket
import sys
from collections import Counter
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from types import FrameType, ModuleType

import pytest

UNIT = "unit"
INTEGRATION = "integration"
KINDS = (UNIT, INTEGRATION)


@dataclass(frozen=True)
class Reach:
    """One kind of reaching outside the test's process."""

    name: str
    """What a failure calls it: "a process", "a socket"."""
    events: frozenset[str]
    """The audit events (docs.python.org/3/library/audit_events.html) that are this reach."""
    detail: Callable[[str, tuple[object, ...]], str | None]
    """What to add to the name for one event ("git" for a process): "" for nothing, or None when
    the event isn't really outside (a socket pair's own loopback on Windows) and isn't counted."""


def _stdlib_file(module: ModuleType) -> str:
    """A standard library module's own source file, as frames name it."""
    return os.path.normcase(os.path.realpath(module.__file__ or ""))


def _called_from(module: ModuleType, functions: frozenset[str] | None = None) -> bool:
    """Whether the audit event being handled was raised under the standard library's `module`
    itself (its own file, not another of that name), in one of `functions` when given."""
    target = _stdlib_file(module)
    frame: FrameType | None = sys._getframe(1)
    while frame is not None:
        code = frame.f_code
        in_function = functions is None or code.co_name in functions
        if in_function and os.path.normcase(os.path.realpath(code.co_filename)) == target:
            return True
        frame = frame.f_back
    return False


def _program(event: str, args: tuple[object, ...]) -> str | None:
    """The program a process runs, as its file name; the event's name when its args don't say.
    None for one the standard library's `platform` module starts (`uname`, `file`) to describe
    this machine: libraries cache the answer, so it would fall on whichever test asked first in a
    process (design D4)."""
    if _called_from(platform):
        return None
    if event == "subprocess.Popen" and len(args) > 1:
        argv = args[1]
        first = argv[0] if isinstance(argv, list | tuple) and argv else argv
        if isinstance(first, str | bytes | os.PathLike):
            return os.path.basename(os.fsdecode(first))
    return event


_SOCKETPAIR = frozenset({"socketpair", "_fallback_socketpair"})
"""socket.socketpair's names: where the platform has no native pair (Windows), socket.py binds it
to _fallback_socketpair, and that's the name its frame carries."""


def _not_a_socket_pair(event: str, args: tuple[object, ...]) -> str | None:
    """Nothing to add for a socket's connect or bind; None for one socket.socketpair makes: on
    Windows it links the pair through a loopback listener, two ends in this process, not a reach
    outside it."""
    return None if _called_from(socket, _SOCKETPAIR) else ""


OUTSIDE: tuple[Reach, ...] = (
    Reach(
        "a process",
        frozenset(
            {
                "subprocess.Popen",
                "os.posix_spawn",
                "os.spawn",
                "os.exec",
                "os.system",
                "os.fork",
                "os.forkpty",
                "os.startfile",
                "_winapi.CreateProcess",
            }
        ),
        _program,
    ),
    Reach(
        "a socket",
        frozenset({"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg"}),
        _not_a_socket_pair,
    ),
    # A git theatre runs git to build its template once per process, then hands out copies: the test
    # that happens to build it would be the only one seen starting git. Core's gitrepo test helper
    # raises this event for every repository it hands out, so every test with one is integration.
    Reach("a git theatre", frozenset({"troupe.tests.theatre"}), lambda event, args: ""),
)
"""Every kind of reach that makes a test integration: the one place to add one (design D4). Add an
example of it to EXAMPLES in scripts/tests/integration/test_kinds_pytest_runs.py too, or that test
fails."""

_BY_EVENT: dict[str, Reach] = {event: reach for reach in OUTSIDE for event in reach.events}


def reached(event: str, args: tuple[object, ...]) -> str | None:
    """What one audit event reached, as a failure names it ("a process (git)"), or None."""
    reach = _BY_EVENT.get(event)
    if reach is None:
        return None
    detail = reach.detail(event, args)
    if detail is None:
        return None
    return f"{reach.name} ({detail})" if detail else reach.name


def suite_of(path: str, suites: list[str]) -> str | None:
    """The suite (the longest `testpaths` entry) holding a repository-relative POSIX path."""
    holding = [s.rstrip("/") for s in suites if path.startswith(s.rstrip("/") + "/")]
    return max(holding, key=len) if holding else None


def kind_of(path: str, suites: list[str]) -> str | None:
    """A test file's kind: the directory directly under its suite, or None when that's neither
    unit/ nor integration/, or the file is under no suite."""
    suite = suite_of(path, suites)
    if suite is None:
        return None
    first, _, rest = path[len(suite) + 1 :].partition("/")
    return first if first in KINDS and rest else None


def imported_tests(source: str) -> list[str]:
    """The test modules a module's source imports, at any depth: `from test_x import ...` or
    `import test_x`. No test module imports another; what tests share lives in a helper beside both
    kinds (design D3a)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        found.update(name for name in names if name.split(".")[0].startswith("test_"))
    return sorted(found)


_RECORDING: list[Counter[str]] = []
_FIXTURES: dict[int, Counter[str]] = {}
"""What each broader-scoped fixture's latest setup reached, by its definition. A fixture set up
again (for another parameter, say) replaces its record, as it replaces its cached value."""
_TEARING_DOWN: set[int] = set()
"""Broader-scoped fixtures being torn down: what they reach then is no test's (design D4)."""
_OWN = pytest.StashKey[Counter[str]]()
_PROBLEMS = pytest.StashKey[list[str]]()
_TIMES: dict[str, dict[str, float]] = {kind: {} for kind in KINDS}


def _record(event: str, args: tuple[object, ...]) -> None:
    """The audit hook. It must never raise: an exception here would fail the call it watches."""
    if not _RECORDING or _TEARING_DOWN or event not in _BY_EVENT:
        return
    with contextlib.suppress(Exception):
        what = reached(event, args)
        if what is not None:
            for window in _RECORDING:
                window[what] += 1


@contextlib.contextmanager
def _window() -> Generator[Counter[str]]:
    seen: Counter[str] = Counter()
    _RECORDING.append(seen)
    try:
        yield seen
    finally:
        # By identity: two windows can hold equal counters (both empty, say).
        del _RECORDING[next(i for i, open_ in enumerate(_RECORDING) if open_ is seen)]


def pytest_configure(config: pytest.Config) -> None:
    for kind in KINDS:
        config.addinivalue_line(
            "markers",
            f"{kind}: under a suite's {kind}/ directory; given by kinds_pytest, never by hand",
        )
    sys.addaudithook(_record)  # one per process; it can't be removed, so it checks _RECORDING


def _relative(config: pytest.Config, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(Path(config.rootpath).resolve()).as_posix()
    except ValueError:
        return None


def _imports_problem(path: Path, seen: dict[Path, str | None]) -> str | None:
    if path not in seen:
        try:
            imported = imported_tests(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            imported = []
        seen[path] = (
            f"{path.name} imports the test module {', '.join(imported)}; no test module imports "
            "another, so move what it uses to a helper module in the suite's tests/ directory, "
            "beside unit/ and integration/"
            if imported
            else None
        )
    return seen[path]


def _place_problem(relative: str, suites: list[str]) -> str:
    suite = suite_of(relative, suites)
    where = f"{suite}/unit/ or {suite}/integration/" if suite else "a suite's unit/ or integration/"
    return f"{relative} is in neither kind's directory; move it to {where}"


class _Unplaced(pytest.File):
    """A test file in neither kind's directory: collecting it fails, naming the fix, so the run
    stops whatever `-m` selects, in one process or across workers (design D5)."""

    problem = ""

    def collect(self) -> list[pytest.Item]:
        raise self.CollectError(f"kinds: {self.problem}")


def pytest_collect_file(file_path: Path, parent: pytest.Collector) -> pytest.Collector | None:
    config = parent.config
    if not any(fnmatch.fnmatch(file_path.name, p) for p in config.getini("python_files")):
        return None
    relative = _relative(config, file_path)
    suites = [Path(entry).as_posix() for entry in config.getini("testpaths")]
    if relative is None or kind_of(relative, suites) is not None:
        return None
    unplaced = _Unplaced.from_parent(parent, path=file_path, name=f"{file_path.name} (kinds)")
    unplaced.problem = _place_problem(relative, suites)
    return unplaced


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tag each test with its directory's kind before `-m` deselects (design D5). A test in
    neither directory has failed its file's collection already (pytest_collect_file)."""
    suites = [Path(entry).as_posix() for entry in config.getini("testpaths")]
    imports: dict[Path, str | None] = {}
    for item in items:
        problems = [p for p in [_imports_problem(item.path, imports)] if p]
        written = sorted({mark.name for mark in item.iter_markers() if mark.name in KINDS})
        if written:
            problems.append(
                f"`{'`, `'.join(written)}` is written by hand; a test's kind is its directory "
                "(unit/ or integration/), so remove the mark"
            )
        relative = _relative(config, item.path)
        kind = kind_of(relative, suites) if relative is not None else None
        if kind is None:
            # Only reached with --continue-on-collection-errors: the test still fails.
            problems.append(_place_problem(relative or str(item.path), suites))
        for name in KINDS if kind is None else (kind,):
            item.add_marker(name)
        if problems:
            item.stash[_PROBLEMS] = problems


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(
    fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest
) -> Generator[None, object, object]:
    """Record what a broader-scoped fixture's setup reaches, for every test that uses it, even
    after an earlier test set it up. A function-scoped fixture is set up inside its test's own
    window, so it needs nothing more. A broader one's teardown runs in whichever test comes last,
    so recording pauses from its first finalizer to its last (finalizers run last-in, first-out)."""
    if fixturedef.scope == "function":
        return (yield)
    key = id(fixturedef)
    fixturedef.addfinalizer(lambda: _TEARING_DOWN.discard(key))  # runs last
    with _window() as seen:
        result = yield
    _FIXTURES[key] = seen
    fixturedef.addfinalizer(lambda: _TEARING_DOWN.add(key))  # runs first
    return result


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(
    item: pytest.Item, nextitem: pytest.Item | None
) -> Generator[None, object, object]:
    with _window() as seen:
        item.stash[_OWN] = seen
        return (yield)


def _used_fixtures(item: pytest.Item) -> list[pytest.FixtureDef[object]]:
    """The fixture definitions the test was actually given: pytest's own record of them, which
    resolves overrides and includes any reached through request.getfixturevalue; the closest
    definition of each name when that record isn't there."""
    request = getattr(item, "_request", None)
    used = getattr(request, "_fixture_defs", None)
    if isinstance(used, dict):
        return list(used.values())
    info = getattr(item, "_fixtureinfo", None)
    return [defs[-1] for defs in getattr(info, "name2fixturedefs", {}).values() if defs]


def _reached(item: pytest.Item) -> Counter[str]:
    """What the test reached: in its own setup, call and teardown (its function-scoped fixtures
    included), and in the setup of each broader-scoped fixture it was given."""
    found: Counter[str] = Counter()
    if _OWN in item.stash:
        own: Counter[str] = item.stash[_OWN]
        found.update(own)
    for definition in _used_fixtures(item):
        if definition.scope != "function":
            found.update(_FIXTURES.get(id(definition), Counter()))
    return found


def _kind(item: pytest.Item) -> str | None:
    names = {mark.name for mark in item.iter_markers() if mark.name in KINDS}
    return names.pop() if len(names) == 1 else None


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if call.when != "teardown":
        return report
    problems: list[str] = []
    if _PROBLEMS in item.stash:
        noted: list[str] = item.stash[_PROBLEMS]
        problems.extend(noted)
    if _kind(item) == UNIT:
        found = _reached(item)
        if found:
            what = ", ".join(f"{name} x{count}" for name, count in sorted(found.items()))
            problems.append(
                f"a unit test reached outside its process: {what}. Move it to integration/, "
                "or keep it in-process"
            )
    if problems and report.outcome != "failed":
        report.outcome = "failed"
        report.longrepr = "\n".join(f"kinds: {problem}" for problem in problems)
    return report


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Add each test's time to its kind's sum, from its three reports (on the controller under
    xdist, where each report carries the test's markers as keywords)."""
    kinds = [kind for kind in KINDS if kind in report.keywords]
    if len(kinds) == 1:
        times = _TIMES[kinds[0]]
        times[report.nodeid] = times.get(report.nodeid, 0.0) + report.duration


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Each kind's count and summed time, on every run (design D6)."""
    if hasattr(terminalreporter.config, "workerinput"):
        return
    for kind in KINDS:
        times = _TIMES[kind]
        if times:
            terminalreporter.write_line(
                f"kinds: {kind}: {len(times)} tests, {sum(times.values()):.1f}s summed"
            )
