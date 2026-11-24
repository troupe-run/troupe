"""A push is judged on its own only when its previous head's latest `check` passed; anything else
diffs the whole pull request, and a malformed input is refused (spec: quality-check; ci-check-scope
D1, ci-once-per-commit D3).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_check_range_integration.py."""

import pytest
from check_range_shared import BASE, BEFORE, EARLY, HEAD, LATE, WHOLE, check_run

import check_range


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
