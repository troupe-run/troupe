"""A push is judged on its own only when its previous head's latest `check` passed; anything else
diffs the whole pull request, and a malformed input is refused (spec: quality-check; ci-check-scope
D1, ci-once-per-commit D3)."""

import json
import subprocess
import sys
from pathlib import Path

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


@pytest.mark.parametrize("action", ["opened", "reopened", "ready_for_review"])
@pytest.mark.parametrize("before", ["", BEFORE])
def test_an_opened_reopened_or_ready_pull_request_diffs_its_whole_change_whatever_before_says(
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
    assert "opened, reopened, synchronize, ready_for_review" in str(refused.value)


def check_run(conclusion: str | None, started_at: str | None) -> dict[str, str | None]:
    return {"status": "completed", "conclusion": conclusion, "started_at": started_at}


EARLY, LATE = "2026-10-30T13:27:32Z", "2026-10-30T13:40:05Z"


def test_no_check_runs_have_no_conclusion() -> None:
    assert check_range.latest_conclusion({"check_runs": []}) == ""


def test_the_check_run_that_started_last_decides() -> None:
    runs = [check_run("failure", EARLY), check_run("success", LATE)]
    assert check_range.latest_conclusion({"check_runs": runs}) == "success"


@pytest.mark.parametrize("later", ["failure", "skipped", "cancelled", None])
def test_an_earlier_success_behind_a_later_run_that_did_not_pass_does_not_count(
    later: str | None,
) -> None:
    runs = [check_run(later, LATE), check_run("success", EARLY)]
    assert check_range.latest_conclusion({"check_runs": runs}) != "success"


def test_a_drafts_skipped_check_then_a_ready_run_in_progress_does_not_narrow() -> None:
    # The draft run's `check` is skipped; the ready run's has started and not finished.
    in_progress = {"status": "in_progress", "conclusion": None, "started_at": LATE}
    document = {"check_runs": [check_run("skipped", EARLY), in_progress]}
    conclusion = check_range.latest_conclusion(document)
    assert check_range.revisions("synchronize", BEFORE, BASE, HEAD, conclusion) == WHOLE


def test_a_drafts_skipped_check_alone_does_not_narrow() -> None:
    conclusion = check_range.latest_conclusion({"check_runs": [check_run("skipped", EARLY)]})
    assert check_range.revisions("synchronize", BEFORE, BASE, HEAD, conclusion) == WHOLE


def test_a_check_run_with_no_start_time_counts_as_the_latest() -> None:
    runs = [check_run("success", LATE), check_run(None, None)]
    assert check_range.latest_conclusion({"check_runs": runs}) == ""


def test_runs_tied_for_latest_pass_only_when_all_passed() -> None:
    tied = [check_run("success", LATE), check_run("failure", LATE)]
    assert check_range.latest_conclusion({"check_runs": tied}) == "failure"
    both = [check_run("success", LATE), check_run("success", LATE)]
    assert check_range.latest_conclusion({"check_runs": both}) == "success"


@pytest.mark.parametrize(
    ("document", "named"),
    [
        ([], "`check_runs` list"),
        ({"total_count": 0}, "`check_runs` list"),
        ({"check_runs": ["check"]}, "check run 0 isn't an object"),
        ({"check_runs": [check_run("success", "yesterday")]}, "started_at `yesterday`"),
        ({"check_runs": [{"conclusion": "success", "started_at": 7}]}, "started_at `7`"),
        ({"check_runs": [{"conclusion": 1, "started_at": LATE}]}, "conclusion `1`"),
    ],
)
def test_check_runs_of_the_wrong_shape_are_refused_naming_what_is_wrong(
    document: object, named: str
) -> None:
    with pytest.raises(check_range.RangeError) as refused:
        check_range.latest_conclusion(document)
    assert named in str(refused.value)


def runs_file(tmp_path: Path, *runs: dict[str, str | None]) -> str:
    path = tmp_path / "check-runs.json"
    path.write_text(json.dumps({"total_count": len(runs), "check_runs": list(runs)}), "utf-8")
    return str(path)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_range.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_script_narrows_on_a_passing_latest_check_and_exits_0(tmp_path: Path) -> None:
    passed = runs_file(tmp_path, check_run("skipped", EARLY), check_run("success", LATE))
    result = run("synchronize", BEFORE, BASE, HEAD, passed)
    assert (result.returncode, result.stdout, result.stderr) == (0, f"{BEFORE} {HEAD}\n", "")


def test_the_script_diffs_the_whole_pull_request_with_no_check_runs() -> None:
    result = run("synchronize", BEFORE, BASE, HEAD, "")
    assert (result.returncode, result.stdout, result.stderr) == (0, f"{WHOLE}\n", "")


def test_a_refusal_exits_1_and_prints_nothing_on_stdout(tmp_path: Path) -> None:
    result = run("synchronize", "", BASE, HEAD, runs_file(tmp_path, check_run("success", LATE)))
    assert (result.returncode, result.stdout) == (1, "")
    assert result.stderr.startswith("check_range: BEFORE ``")


@pytest.mark.parametrize("args", [(), ("synchronize", BEFORE, BASE, HEAD)])
def test_a_wrong_number_of_arguments_fails_naming_what_to_pass(args: tuple[str, ...]) -> None:
    result = run(*args)
    assert (result.returncode, result.stdout) == (1, "")
    assert f"expected 5 arguments (ACTION BEFORE BASE HEAD CHECK_RUNS), got {len(args)}" in (
        result.stderr
    )


@pytest.mark.parametrize("content", ["not json", '{"check_runs": "none"}'])
def test_unreadable_check_runs_exit_1_naming_the_file(tmp_path: Path, content: str) -> None:
    path = tmp_path / "check-runs.json"
    path.write_text(content, encoding="utf-8")
    result = run("synchronize", BEFORE, BASE, HEAD, str(path))
    assert (result.returncode, result.stdout) == (1, "")
    assert f"CHECK_RUNS `{path}`" in result.stderr


def test_a_missing_check_runs_file_exits_1_naming_it(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    result = run("synchronize", BEFORE, BASE, HEAD, str(missing))
    assert (result.returncode, result.stdout) == (1, "")
    assert f"CHECK_RUNS `{missing}` can't be read" in result.stderr
