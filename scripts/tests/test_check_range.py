"""A push is judged on its own only when its previous head passed `check`; anything else diffs the
whole pull request, and a malformed input is refused (spec: quality-check; ci-check-scope D1)."""

import subprocess
import sys

import pytest
from conftest import REPO

import check_range

BEFORE, BASE, HEAD = "a" * 40, "b" * 40, "c" * 40
WHOLE = f"{BASE}...{HEAD}"


def test_a_push_after_a_passing_check_diffs_the_two_heads_directly() -> None:
    assert check_range.revisions("synchronize", BEFORE, BASE, HEAD, "success") == f"{BEFORE} {HEAD}"


@pytest.mark.parametrize(
    "conclusion", ["", "failure", "cancelled", "skipped", "timed_out", "neutral", "Success"]
)
def test_a_push_after_any_other_conclusion_diffs_the_whole_pull_request(conclusion: str) -> None:
    assert check_range.revisions("synchronize", BEFORE, BASE, HEAD, conclusion) == WHOLE


@pytest.mark.parametrize("action", ["opened", "reopened"])
@pytest.mark.parametrize("before", ["", BEFORE])
def test_an_opened_or_reopened_pull_request_diffs_its_whole_change_whatever_before_says(
    action: str, before: str
) -> None:
    assert check_range.revisions(action, before, BASE, HEAD, "success") == WHOLE


@pytest.mark.parametrize(
    ("action", "before", "base", "head", "named"),
    [
        ("synchronize", "", BASE, HEAD, "BEFORE ``"),
        ("synchronize", "A" * 40, BASE, HEAD, f"BEFORE `{'A' * 40}`"),
        ("synchronize", BEFORE, "b" * 39, HEAD, f"BASE `{'b' * 39}`"),
        ("synchronize", BEFORE, BASE, "main", "HEAD `main`"),
        ("opened", "not-a-sha", BASE, HEAD, "BEFORE `not-a-sha`"),
        ("opened", "", "", HEAD, "BASE ``"),
    ],
)
def test_a_malformed_sha_is_refused_naming_it(
    action: str, before: str, base: str, head: str, named: str
) -> None:
    with pytest.raises(check_range.RangeError, match="40 lowercase hex characters") as refused:
        check_range.revisions(action, before, base, head, "success")
    assert named in str(refused.value)


@pytest.mark.parametrize("action", ["edited", "closed", "", "Synchronize"])
def test_an_action_ci_doesnt_run_on_is_refused_naming_it_and_the_valid_ones(action: str) -> None:
    with pytest.raises(check_range.RangeError) as refused:
        check_range.revisions(action, BEFORE, BASE, HEAD, "success")
    assert f"action `{action}`" in str(refused.value)
    assert "opened, reopened, synchronize" in str(refused.value)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_range.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_script_prints_the_revisions_and_exits_0() -> None:
    result = run("synchronize", BEFORE, BASE, HEAD, "success")
    assert (result.returncode, result.stdout, result.stderr) == (0, f"{BEFORE} {HEAD}\n", "")


def test_a_refusal_exits_1_and_prints_nothing_on_stdout() -> None:
    result = run("synchronize", "", BASE, HEAD, "success")
    assert (result.returncode, result.stdout) == (1, "")
    assert result.stderr.startswith("check_range: BEFORE ``")


@pytest.mark.parametrize("args", [(), ("synchronize", BEFORE, BASE, HEAD)])
def test_a_wrong_number_of_arguments_fails_naming_what_to_pass(args: tuple[str, ...]) -> None:
    result = run(*args)
    assert (result.returncode, result.stdout) == (1, "")
    assert f"expected 5 arguments (ACTION BEFORE BASE HEAD CONCLUSION), got {len(args)}" in (
        result.stderr
    )
