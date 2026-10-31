"""The tests gate's command behaves in parallel the way run_gates relies on: no tests selected exits
5, a failing test exits 1 and is named, the slowest tests' durations print either way, and a test
past the stall limit has its stack written from inside its worker (spec: quality-check;
parallel-tests design D1-D3; shorten-slow-tests design D4; windows-ci-hang design D1).

Each run is a real pytest with check.py's own PARALLEL and DURATIONS options, in a directory
pytester writes, with the worker count pinned to 2 through xdist's own variable."""

import sys
import tomllib
from pathlib import Path

import pytest

import check

pytest_plugins = ["pytester"]


@pytest.fixture
def suite(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "2")
    pytester.makeini("[pytest]\nmarkers =\n    docs: reads the docs\n")
    pytester.makepyfile(
        test_some="def test_passes():\n    pass\n\n\ndef test_fails():\n    assert 1 == 2\n\n\n"
        "def test_also_passes():\n    pass\n"
    )
    return pytester


def gate_command(*args: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        *check.PARALLEL,
        *check.DURATIONS,
        *args,
    ]


def test_a_parallel_run_that_selects_no_tests_exits_no_tests_ran(suite: pytest.Pytester) -> None:
    result = suite.run(*gate_command("-m", "docs"))

    result.stdout.fnmatch_lines(["created: 2/2 workers"])
    assert result.ret == check.NO_TESTS_RAN


def test_a_parallel_run_with_a_failing_test_exits_1_and_names_it(suite: pytest.Pytester) -> None:
    result = suite.run(*gate_command("-rf"))

    result.stdout.fnmatch_lines(["created: 2/2 workers"])
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(["FAILED test_some.py::test_fails - assert 1 == 2"])
    result.assert_outcomes(passed=2, failed=1)


def test_a_scoped_check_whose_parallel_tests_gate_selects_nothing_passes_and_says_so(
    suite: pytest.Pytester, capfd: pytest.CaptureFixture[str]
) -> None:
    code = check.run_gates([("tests", gate_command("-m", "docs"))], suite.path, ("docs",))

    output = capfd.readouterr().out
    assert code == 0, output
    assert "created: 2/2 workers" in output
    assert "no test is tagged `docs`, so there was nothing to test" in output


def test_a_parallel_tests_gate_with_a_failing_test_stops_the_check_naming_the_gate(
    suite: pytest.Pytester, capfd: pytest.CaptureFixture[str]
) -> None:
    code = check.run_gates([("tests", gate_command()), ("after", gate_command())], suite.path)

    output = capfd.readouterr().out
    assert code == pytest.ExitCode.TESTS_FAILED
    assert "check: tests failed (exit 1)" in output
    assert "==> after" not in output


def test_a_parallel_run_that_passes_prints_the_slowest_durations_across_the_workers(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "2")
    pytester.makepyfile(
        test_slow="import time\n\n\ndef test_slowest():\n    time.sleep(0.3)\n\n\n"
        "def test_quick():\n    pass\n"
    )
    result = pytester.run(*gate_command())

    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["created: 2/2 workers", "*slowest 25 durations*"])
    result.stdout.fnmatch_lines(["0.[3-9]*s call *test_slow.py::test_slowest"])


def test_a_parallel_run_with_a_failing_test_still_prints_the_slowest_durations(
    suite: pytest.Pytester,
) -> None:
    result = suite.run(*gate_command())

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(["*slowest 25 durations*"])
    result.stdout.fnmatch_lines(["FAILED test_some.py::test_fails*"])


def test_the_full_and_the_scoped_tests_gates_ask_for_the_slowest_durations() -> None:
    for scopes in [(), ("docs",)]:
        tests = dict(check.gates(scopes))["tests"]
        assert tests[1 : 1 + len(check.PARALLEL) + 1] == [*check.PARALLEL, "--durations=25"]


STALL_LIMIT = 1
"""The stall limit these tests give pytest, in seconds: short, so a test can pass it quickly."""


SLEEP_LINE = 5
"""The line of the stuck test's sleep in the file _stall_suite writes. A dump that names it was
taken while the test was still sleeping, not after the test had finished."""


def _stall_suite(pytester: pytest.Pytester, sleep: float) -> None:
    pytester.makeini(f"[pytest]\nfaulthandler_timeout = {STALL_LIMIT}\n")
    pytester.makepyfile(
        test_stall=f"import time\n\n\ndef test_stuck_here():\n    time.sleep({sleep})\n\n\n"
        "def test_quick():\n    pass\n"
    )


def test_a_test_past_the_stall_limit_in_a_parallel_run_has_its_stack_in_the_output(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "2")
    _stall_suite(pytester, sleep=STALL_LIMIT + 1.5)
    result = pytester.run(*gate_command())

    output = "\n".join([*result.outlines, *result.errlines])
    assert result.ret == pytest.ExitCode.OK, output
    assert f"Timeout (0:00:0{STALL_LIMIT})!" in output, output
    assert any(
        "test_stall.py" in line and f"line {SLEEP_LINE} in test_stuck_here" in line
        for line in output.splitlines()
    ), output
    result.assert_outcomes(passed=2)


def test_a_parallel_run_with_no_test_past_the_stall_limit_dumps_no_stack(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "2")
    _stall_suite(pytester, sleep=0)
    result = pytester.run(*gate_command())

    output = "\n".join([*result.outlines, *result.errlines])
    assert result.ret == pytest.ExitCode.OK, output
    assert "Timeout (" not in output, output


SLOWEST_TEST_MARGIN = 120
"""The stall limit must be above this many seconds: the slowest test takes 87 s on Windows CI."""
STALL_LIMIT_CEILING = 600
"""...and at most this many: the CI job's 20 minutes, less a Windows suite of up to 10 minutes."""


def test_the_repositorys_stall_limit_is_set_above_the_slowest_test_and_below_the_jobs_room() -> (
    None
):
    pyproject = Path(check.ROOT, "pyproject.toml").read_text(encoding="utf-8")
    options = tomllib.loads(pyproject)["tool"]["pytest"]["ini_options"]

    assert "faulthandler_timeout" in options, "pyproject.toml sets no stall limit"
    assert SLOWEST_TEST_MARGIN < options["faulthandler_timeout"] <= STALL_LIMIT_CEILING
