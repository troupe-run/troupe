"""Fails a test that leaves a stand-in claude running, and stops it (spec: claude-code-runner,
"A test that leaves a stand-in running fails"; reap-fake-claude design D3).

Loaded by a ``conftest.py`` in each suite that starts the stand-in: the plugin's own, and core's,
which loads this file by path. conftest hooks apply only to tests in their own directory, so each
test is checked once and no other suite loads this.

At configure it points ``FAKE_CLAUDE_LEDGER`` at a ledger named by this process's pid, which
``install()`` writes into every shim. Each test's teardown, once every fixture's own has run, looks
at every stand-in in the ledger: each check forgets what it has seen, so those are the ones started
since the last check. One still holding its lock after
``STAND_IN_END_SECONDS`` is stopped, and the test fails naming it. Only a held lock counts as
running, so a pid the OS has given to another process is never signalled.

A stand-in still starting up has no entry yet, but it's in its runner's process group or job, and
ends with the runner. One that escaped those before it recorded itself is caught by the next test's
check in this process, which names its working directory (under the test it came from), or, after
the last test, stopped by the sweep at unconfigure.

A stand-in has to be started and ended within one test: one started by a module- or session-scoped
fixture would still be running at its first test's check.
"""

import importlib.util
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Generator
from pathlib import Path
from types import ModuleType

import pytest

STAND_IN_END_SECONDS = 5.0
"""How long a stand-in started during a test has to end once the test's teardown has run, and then
again once it has been stopped. A kill of the runner's group ends it within milliseconds. The rest
is room for Windows, which releases a dead process's lock "after an unspecified time". The same
as the runner's CLAUDE_STOP_GRACE_SECONDS."""

_POLL_SECONDS = 0.02


def _load_fake() -> ModuleType:
    """The stand-in's module, by path, so this works from core's tests as well as the plugin's."""
    spec = importlib.util.spec_from_file_location(
        "stand_in_guard_fake_claude", Path(__file__).with_name("fake_claude.py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("the stand-in claude can't be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_fake = _load_fake()


def ledger() -> Path:
    """This process's ledger. Worked out from the pid, so every copy of this module in one process
    agrees on it, and each xdist worker has its own."""
    return Path(tempfile.gettempdir()) / f"troupe-stand-ins-{os.getpid()}"


def pytest_configure(config: pytest.Config) -> None:
    # Empty, so an entry left by an earlier run whose pytest had this pid isn't counted.
    shutil.rmtree(ledger(), ignore_errors=True)
    ledger().mkdir(exist_ok=True)
    os.environ[_fake.LEDGER] = str(ledger())  # replaces a value inherited from xdist's controller


def pytest_unconfigure(config: pytest.Config) -> None:
    """Stop any stand-in still running, so none outlives the run, then remove the ledger."""
    for pid in _fake.ledger_entries(ledger()):
        if _fake.still_running(ledger(), pid):
            _fake.stop(pid)
            _ends(ledger(), pid)
    shutil.rmtree(ledger(), ignore_errors=True)


def _within(seconds: float, done: Callable[[], bool]) -> bool:
    """Whether ``done`` came true within ``seconds``, polling."""
    deadline = time.monotonic() + seconds
    while not done():
        if time.monotonic() > deadline:
            return False
        time.sleep(_POLL_SECONDS)
    return True


def _ends(path: Path, pid: int) -> bool:
    """Whether the stand-in ``pid`` has ended, or does within ``STAND_IN_END_SECONDS``."""
    return _within(STAND_IN_END_SECONDS, lambda: not _fake.still_running(path, pid))


def _left_running(path: Path, pid: int) -> str | None:
    """None when the stand-in ``pid`` has ended, otherwise what's wrong, once it's stopped."""
    if _ends(path, pid):
        return None
    record = _fake.described(path, pid)
    cwd = record.get("cwd", "not recorded yet") if record else "not recorded yet"
    _fake.stop(pid)
    stopped = _ends(path, pid)
    return (
        f"stand-in claude {pid} (working directory {cwd}) was still running "
        f"{STAND_IN_END_SECONDS:g}s after the test ended; "
        + ("it has been stopped" if stopped else "stopping it didn't end it within that time")
    )


def left_running(path: Path) -> list[str]:
    """What's wrong with each stand-in in the ledger that hadn't ended once the test was over,
    stopping each one. Every entry is then forgotten, so each is counted once: the ledger holds
    only stand-ins no check has seen. Empty when all had ended."""
    problems = []
    for pid in sorted(_fake.ledger_entries(path)):
        if (problem := _left_running(path, pid)) is not None:
            problems.append(problem)
        _fake.forget(path, pid)
    return problems


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(
    item: pytest.Item, nextitem: pytest.Item | None
) -> Generator[None, object, object]:
    try:
        return (yield)
    finally:
        if problems := left_running(ledger()):
            pytest.fail(
                "The test left a stand-in claude running. End the runner as troupe does (kill its "
                "process group), or stop the stand-in before the test ends:\n- "
                + "\n- ".join(problems),
                pytrace=False,
            )
