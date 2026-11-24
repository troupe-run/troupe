"""The Bug a failed release install check opens names the tag, each failed leg and the run, and no
issue is opened when every leg passed (spec: installation; install-from-tag design D6).

The jobs are a real `gh run view --json jobs` payload: CI run 41181494838, trimmed to a few jobs
and one step each. Its matrix legs are renamed from `check (...)` to `install (...)`, the name the
release install check's matrix job gives them, since that workflow hasn't run yet.

Its tests that start a process, open a socket or use a git theatre are in
integration/test_release_check_report_integration.py."""

import pytest
from release_check_report_shared import JOBS, RELEASE, RUN, TAG, failing

import release_check_report
from release_check_report import Failed


def test_every_leg_passing_gives_no_failed_legs() -> None:
    assert release_check_report.failed_legs(JOBS) == []


def test_one_failed_leg_is_named_by_platform_python_result_and_job() -> None:
    assert release_check_report.failed_legs(failing(("windows-latest", "3.15", "failure"))) == [
        Failed("Windows", "3.15", "failure", f"{RUN}/job/124479681805")
    ]


def test_several_failed_legs_are_in_platform_then_python_order_and_other_jobs_are_ignored() -> None:
    jobs = failing(
        ("windows-latest", "3.15", "failure"),
        ("macos-latest", "3.13", "timed_out"),
        ("windows-latest", "3.12", "cancelled"),
    )
    jobs["jobs"][0]["conclusion"] = "failure"  # not an install leg
    assert release_check_report.failed_legs(jobs) == [
        Failed("Windows", "3.12", "cancelled", f"{RUN}/job/124479681847"),
        Failed("Windows", "3.15", "failure", f"{RUN}/job/124479681805"),
        Failed("macOS", "3.13", "timed_out", f"{RUN}/job/124479681743"),
    ]


def test_the_issue_is_a_bug_naming_the_tag_each_failed_leg_the_run_and_the_release() -> None:
    failed = [Failed("Windows", "3.15", "failure", f"{RUN}/job/124479681805")]
    opened = release_check_report.issue(failed, TAG, RUN, RELEASE)
    assert opened["title"] == "Install check failed for troupe-run-v0.1.0"
    assert opened["type"] == "Bug"
    body = opened["body"]
    assert "for `troupe-run-v0.1.0`" in body
    assert f"| Windows | 3.15 | failure | [job]({RUN}/job/124479681805) |" in body
    assert f"- Run: {RUN}\n" in body
    assert f"- Release: {RELEASE}\n" in body
    assert "gh workflow run release-install-check.yml -f ref=troupe-run-v0.1.0" in body
    assert "tags are never moved or deleted" in body
    assert "Add this issue to the troupe roadmap board" in body


@pytest.mark.parametrize("argv", [[], ["jobs.json", TAG]])
def test_the_script_refuses_the_wrong_arguments_with_its_usage(argv: list[str]) -> None:
    assert release_check_report.main(argv) == 2
