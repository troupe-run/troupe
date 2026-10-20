# Source: troupe-run/infrastructure. Change it there; copies in other repositories are delivered.
"""pytest plugin: each test's markers must cover what it reads (spec: development-workflow).

Load it from the repository's pytest configuration, with scripts/ on pytest's pythonpath:

    addopts = ["-p", "guard_pytest"]

It reads scripts/check-paths.toml, registers each scope as a marker (so --strict-markers accepts
them and the declaration is the one list), and adds a scope's marker to every collected test under
one of its `tests` directories, before `-m` selects, so a scope can run whole suites. A `tests`
entry that no collected test is under is reported as a failing test carrying that scope's marker,
so the full run and the scope's own run both fail (scope-test-directories design D5). It also
records every file inside the repository opened for a test, through Python's `open` audit event. A
test's reads are what it opens during its own setup, call and teardown, what its module and the
collectors above it open while being collected (a module-level `TEXT = DOC.read_text()`, or
parameters built from a file), and what each fixture it uses opens while being set up, even when an
earlier test set that fixture up. A test that reads a skipped path, or a scope's path without that
scope's marker, then fails at teardown with the guard's message. The rule itself is
guard.tag_violations, which takes plain data so another runner's adapter can use it too
(commit-check-paths design D9).

A file Hypothesis opens to collect constants isn't the test's read. Before a draw, it reads the
source of every first-party module imported since its last draw, whichever test imported it
(guard-hypothesis-reads design D1). What the test opens itself, in a @given body or a strategy,
still counts.

Reads made by a subprocess the test starts aren't seen: the hook watches this process only.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Generator
from pathlib import Path
from types import FrameType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard

_ROOT: str | None = None
_DECLARATION: guard.CheckPaths | None = None
_RECORDING: list[set[str]] = []
"""The reads being recorded now: one set per open window (a collector, a fixture, a test). A
read joins every open window, so an outer window also holds what an inner one read."""
_COLLECTED: dict[str, frozenset[str]] = {}
"""Reads made while each collector (by node id) collected its children."""
_FIXTURES: dict[int, set[str]] = {}
"""Reads made while each fixture definition (by id) was set up, over every setup."""
_OWN_READS = pytest.StashKey[set[str]]()
_HYPOTHESIS_CONSTANTS = "hypothesis/internal/constants_ast.py"
"""Where Hypothesis reads a module's source for its constants (guard-hypothesis-reads design D1).
An open made while it's on the stack is Hypothesis's own, not the test's."""


def _record(event: str, args: tuple[object, ...]) -> None:
    """The audit hook. It must never raise: an exception here would fail the open itself."""
    if event != "open" or not _RECORDING or _ROOT is None:
        return
    with contextlib.suppress(Exception):
        path = args[0]
        if not isinstance(path, str | os.PathLike):
            return  # a file descriptor, or bytes
        relative = _relative(path)
        if not relative:
            return  # outside the repository, or the repository itself
        if _hypothesis_reading():
            return
        for reads in _RECORDING:
            reads.add(relative)


def _hypothesis_reading() -> bool:
    """Whether Hypothesis's constant collection is on the stack of the open being recorded."""
    frame: FrameType | None = sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_filename.replace("\\", "/").endswith(_HYPOTHESIS_CONSTANTS):
            return True
        frame = frame.f_back
    return False


@contextlib.contextmanager
def _window() -> Generator[set[str]]:
    reads: set[str] = set()
    _RECORDING.append(reads)
    try:
        yield reads
    finally:
        # By identity: two windows can hold equal sets (both empty, say), and remove() compares.
        del _RECORDING[next(i for i, open_ in enumerate(_RECORDING) if open_ is reads)]


def pytest_configure(config: pytest.Config) -> None:
    global _ROOT, _DECLARATION
    root = Path(config.rootpath)
    text = guard.read_working_tree(root)(guard.CHECK_PATHS)
    if text is None:
        return
    try:
        _DECLARATION = guard.check_paths(text)
    except guard.CheckPathsError as error:
        raise pytest.UsageError(error.decision().text()) from None
    directories = dict(_DECLARATION.tests)
    for name, entries in _DECLARATION.scopes:
        runs = f"; runs {', '.join(directories[name])}" if name in directories else ""
        config.addinivalue_line(
            "markers", f"{name}: reads {', '.join(entries)}{runs} ({guard.CHECK_PATHS})"
        )
    _ROOT = os.path.realpath(root)
    sys.addaudithook(_record)  # one per process; it can't be removed, so it checks _RECORDING


def _relative(path: str | os.PathLike[str]) -> str | None:
    """A path as the repository-relative POSIX path guard's rules take ("" for the root), or None
    when it's outside the repository or there's no declaration."""
    if _ROOT is None:
        return None
    real = os.path.realpath(os.fspath(path))
    if real == _ROOT:
        return ""
    if not real.startswith(_ROOT + os.sep):
        return None
    return Path(os.path.relpath(real, _ROOT)).as_posix()


def _roots(config: pytest.Config) -> list[str]:
    """What the run was asked to collect (D6): its path arguments, or the whole repository when it
    was given none. `testpaths` then lists the suites, and a stale `tests` entry is outside every
    one of them, so checking only inside `testpaths` would miss the renamed directory it's for."""
    if config.args_source is not pytest.Config.ArgsSource.ARGS:
        return [""]
    roots = []
    for arg in config.args:
        target = Path(config.invocation_params.dir, arg.split("::", 1)[0])
        relative = _relative(target)
        if relative is not None:
            roots.append(relative)
    return roots


class _UnmatchedTests(pytest.Item):
    """A scope's `tests` entry that no collected test is under. It fails, naming the entry."""

    unmatched: guard.UnmatchedTests

    def runtest(self) -> None:
        raise AssertionError(self.unmatched.message)

    def repr_failure(
        self, excinfo: pytest.ExceptionInfo[BaseException], style: object = None
    ) -> str:
        return f"guard: {self.unmatched.message}"

    def reportinfo(self) -> tuple[Path, None, str]:
        return self.path, None, f"{guard.CHECK_PATHS}::{self.unmatched.place}"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Tag each test with the scopes whose `tests` hold its file, before `-m` deselects (D5).

    Every xdist worker collects the same files and so does the same, in the same order, which the
    controller requires of them.
    """
    if _DECLARATION is None or not _DECLARATION.tests:
        return
    files = []
    for item in items:
        relative = _relative(item.path)
        if relative is None:
            continue
        files.append(relative)
        for name in sorted(guard.directory_tags(relative, _DECLARATION)):
            item.add_marker(name)
    failing = []
    for unmatched in guard.unmatched_tests(files, _roots(config), _DECLARATION):
        item = _UnmatchedTests.from_parent(
            session, name=unmatched.place, nodeid=f"{guard.CHECK_PATHS}::{unmatched.place}"
        )
        item.unmatched = unmatched
        item.add_marker(unmatched.scope)
        failing.append(item)
    items[:0] = failing


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector: pytest.Collector) -> Generator[None, object, object]:
    if _DECLARATION is None:
        return (yield)
    with _window() as reads:
        report = yield
    _COLLECTED[collector.nodeid] = frozenset(reads)
    return report


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(
    fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest
) -> Generator[None, object, object]:
    if _DECLARATION is None:
        return (yield)
    with _window() as reads:
        result = yield
    _FIXTURES.setdefault(id(fixturedef), set()).update(reads)
    return result


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(
    item: pytest.Item, nextitem: pytest.Item | None
) -> Generator[None, object, object]:
    if _DECLARATION is None:
        return (yield)
    with _window() as reads:
        item.stash[_OWN_READS] = reads
        return (yield)


def _reads(item: pytest.Item) -> frozenset[str]:
    """Everything opened for this test: its own window, its collectors', and its fixtures'."""
    own: set[str] = item.stash.get(_OWN_READS, set())
    reads = set(own)
    for node in item.listchain():
        reads |= _COLLECTED.get(node.nodeid, frozenset())
    info = getattr(item, "_fixtureinfo", None)  # pytest's own record of the test's fixtures
    for definitions in getattr(info, "name2fixturedefs", {}).values():
        for definition in definitions:
            reads |= _FIXTURES.get(id(definition), set())
    return frozenset(reads)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if call.when != "teardown" or _DECLARATION is None:
        return report
    test = guard.TestReads(
        test=item.nodeid,
        tags=frozenset(mark.name for mark in item.iter_markers()),
        reads=_reads(item),
    )
    found = guard.tag_violations(test, _DECLARATION)
    if found and report.outcome != "failed":
        report.outcome = "failed"
        report.longrepr = "\n".join(f"guard: {violation}" for violation in found)
    return report
