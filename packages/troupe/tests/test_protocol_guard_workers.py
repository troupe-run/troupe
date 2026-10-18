"""The protocol guard's full-run check across pytest-xdist workers (spec: quality-check;
parallel-tests design D4).

The pytester runs are subprocesses: the guard's tally is module state, and this session's own
guard is filling it as these tests run."""

import os
from pathlib import Path

import pytest

import protocol_guard
from troupe.core import errors, notices

pytest_plugins = ["pytester"]

HERE = Path(__file__).resolve().parent
UNEXERCISED = "protocol_guard: no test raised these codes"


@pytest.fixture
def suite(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """A full run's shape: testpaths set, two tests that make troupe raise nothing."""
    path = os.pathsep.join([str(HERE), os.environ.get("PYTHONPATH", "")])
    monkeypatch.setenv("PYTHONPATH", path)
    pytester.makeini("[pytest]\ntestpaths = tests\n")
    pytester.mkdir("tests")
    pytester.path.joinpath("tests", "test_nothing.py").write_text(
        "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n", encoding="utf-8"
    )
    return pytester


def guarded(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    return pytester.runpytest_subprocess("-p", "protocol_guard", "-p", "no:cacheprovider", *args)


def test_a_parallel_full_run_that_raises_no_codes_fails_once_naming_them(
    suite: pytest.Pytester,
) -> None:
    result = guarded(suite, "-n", "2")

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    lines = [line for line in result.outlines if UNEXERCISED in line]
    assert len(lines) == 1, result.stdout.str()
    assert all(code in lines[0] for code in errors.CODES)


def test_a_parallel_run_narrowed_by_k_does_not_check_the_codes(suite: pytest.Pytester) -> None:
    result = guarded(suite, "-n", "2", "-k", "one")

    assert result.ret == pytest.ExitCode.OK
    assert UNEXERCISED not in result.stdout.str()


def test_a_one_process_full_run_that_raises_no_codes_fails_once_naming_them(
    suite: pytest.Pytester,
) -> None:
    result = guarded(suite)

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    lines = [line for line in result.outlines if UNEXERCISED in line]
    assert len(lines) == 1, result.stdout.str()
    assert all(code in lines[0] for code in errors.CODES)


class _Gateway:
    def __init__(self, id: str) -> None:
        self.id = id


class _Node:
    """An xdist worker node as the controller sees it when the worker goes down."""

    def __init__(self, id: str, workeroutput: dict[str, object] | None) -> None:
        self.gateway = _Gateway(id)
        if workeroutput is not None:
            self.workeroutput = workeroutput


@pytest.fixture
def fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty tally, so the merge is seen alone (and this session's own tally is untouched)."""
    monkeypatch.setattr(protocol_guard, "_seen", set())
    monkeypatch.setattr(protocol_guard, "_silent", [])


@pytest.mark.usefixtures("fresh")
def test_codes_split_across_workers_leave_nothing_unraised_though_no_worker_had_them_all() -> None:
    codes = sorted(set(errors.CODES) | set(notices.CODES))
    first, second = codes[::2], codes[1::2]

    protocol_guard.pytest_testnodedown(_Node("gw0", {protocol_guard.SEEN_KEY: first}), None)
    protocol_guard.pytest_testnodedown(_Node("gw1", {protocol_guard.SEEN_KEY: second}), None)

    assert protocol_guard.unraised() == []
    assert protocol_guard._silent == []


@pytest.mark.usefixtures("fresh")
def test_a_worker_that_went_down_without_reporting_its_codes_is_recorded_by_name() -> None:
    protocol_guard.pytest_testnodedown(_Node("gw0", {protocol_guard.SEEN_KEY: []}), None)
    protocol_guard.pytest_testnodedown(_Node("gw1", None), "worker crashed")
    protocol_guard.pytest_testnodedown(_Node("gw2", {"exitstatus": 0}), None)

    assert protocol_guard._silent == ["gw1", "gw2"]
