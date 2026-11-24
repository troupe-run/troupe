"""check.py's gates run for real: a scoped check passes when no tests were tagged and says so, the
full check fails when no tests ran, and a failing gate stops the check and names itself, scoped
or not (spec: quality-check; commit-check-paths design D8).

Its tests that stay in their own process are in unit/test_check_scope.py."""

import sys
from pathlib import Path

import pytest

import check


def exit_code(code: int) -> list[str]:
    return [sys.executable, "-c", f"raise SystemExit({code})"]


def test_no_tests_ran_passes_a_scoped_check_and_says_nothing_was_tagged(
    capfd: pytest.CaptureFixture[str],
) -> None:
    code = check.run_gates([("tests", exit_code(check.NO_TESTS_RAN))], Path.cwd(), ("docs",))
    assert code == 0
    output = capfd.readouterr().out
    assert "no test is tagged `docs`, so there was nothing to test" in output
    assert "check: all gates passed" in output


def test_no_tests_ran_fails_the_full_check(capfd: pytest.CaptureFixture[str]) -> None:
    code = check.run_gates([("tests", exit_code(check.NO_TESTS_RAN))], Path.cwd())
    assert code == check.NO_TESTS_RAN
    assert "check: tests failed (exit 5)" in capfd.readouterr().out


@pytest.mark.parametrize("scopes", [(), ("docs",)], ids=["full", "scoped"])
def test_a_failing_gate_stops_the_check_and_names_itself(
    scopes: tuple[str, ...], capfd: pytest.CaptureFixture[str]
) -> None:
    steps = [("ruff lint", exit_code(1)), ("tests", exit_code(0))]
    assert check.run_gates(steps, Path.cwd(), scopes) == 1
    output = capfd.readouterr().out
    assert "check: ruff lint failed (exit 1)" in output
    assert "==> tests" not in output


def test_a_scoped_check_still_fails_on_a_failing_test_gate(
    capfd: pytest.CaptureFixture[str],
) -> None:
    assert check.run_gates([("tests", exit_code(1))], Path.cwd(), ("docs",)) == 1
    assert "check: tests failed (exit 1)" in capfd.readouterr().out
