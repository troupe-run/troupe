"""The one required `check` passes only when the legs passed, or were skipped because nothing
needed checking (spec: quality-check; ci-check-scope design D3)."""

import subprocess
import sys

import pytest
from conftest import REPO

import check_result


@pytest.mark.parametrize(("changes", "scope"), [("success", "full"), ("", ""), ("failure", "")])
def test_legs_that_all_passed_pass_whatever_changes_answered(changes: str, scope: str) -> None:
    assert check_result.judge("success", changes, scope) == (True, "every leg passed.")


def test_legs_skipped_because_changes_answered_none_pass() -> None:
    passed, reason = check_result.judge("skipped", "success", "none")
    assert passed
    assert "`changes` answered that nothing needs checking" in reason


@pytest.mark.parametrize(
    ("changes", "scope"),
    [
        ("success", "full"),
        ("success", "docs"),
        ("success", ""),
        ("failure", "none"),
        ("skipped", ""),
        ("cancelled", "none"),
    ],
)
def test_legs_skipped_without_a_none_answer_fail_naming_both(changes: str, scope: str) -> None:
    passed, reason = check_result.judge("skipped", changes, scope)
    assert not passed
    assert "skipped without a reason to skip them" in reason
    assert f"changes: `{changes}`" in reason
    assert f"scope: `{scope}`" in reason


@pytest.mark.parametrize("legs", ["failure", "cancelled"])
def test_legs_that_failed_or_were_cancelled_fail_naming_the_result(legs: str) -> None:
    passed, reason = check_result.judge(legs, "success", "none")
    assert not passed
    assert f"`{legs}`" in reason


@pytest.mark.parametrize("legs", ["", "neutral", "Success"])
def test_an_unknown_legs_result_fails_naming_it_and_what_is_valid(legs: str) -> None:
    passed, reason = check_result.judge(legs, "success", "none")
    assert not passed
    assert f"`{legs}`" in reason
    assert "success, failure, cancelled, skipped" in reason


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_result.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_script_exits_0_when_check_passes_and_1_when_it_fails() -> None:
    passed = run("skipped", "success", "none")
    failed = run("failure", "success", "full")
    assert (passed.returncode, failed.returncode) == (0, 1)
    assert passed.stdout.startswith("check: passed, ")
    assert failed.stdout.startswith("check: failed, ")


@pytest.mark.parametrize("args", [(), ("success",), ("success", "success", "none", "extra")])
def test_a_wrong_number_of_arguments_fails_naming_what_to_pass(args: tuple[str, ...]) -> None:
    result = run(*args)
    assert result.returncode == 1
    assert f"expected 3 arguments (LEGS CHANGES SCOPE), got {len(args)}" in result.stderr
