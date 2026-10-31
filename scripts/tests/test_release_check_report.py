"""The Bug a failed release install check opens names the tag, each failed leg and the run, and no
issue is opened when every leg passed (spec: installation; install-from-tag design D6).

The jobs are a real `gh run view --json jobs` payload: CI run 41181494838, trimmed to a few jobs
and one step each. Its matrix legs are renamed from `check (...)` to `install (...)`, the name the
release install check's matrix job gives them, since that workflow hasn't run yet."""

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import SCRIPTS

import release_check_report
from release_check_report import Failed

RUN = "https://github.com/troupe-run/troupe/actions/runs/41181494838"
RELEASE = "https://github.com/troupe-run/troupe/releases/tag/troupe-run-v0.1.0"
TAG = "troupe-run-v0.1.0"


def job(
    name: str, conclusion: str, database_id: int, started: str, completed: str
) -> dict[str, Any]:
    return {
        "completedAt": completed,
        "conclusion": conclusion,
        "databaseId": database_id,
        "name": name,
        "startedAt": started,
        "status": "completed",
        "steps": [
            {
                "completedAt": started,
                "conclusion": "success",
                "name": "Set up job",
                "number": 1,
                "startedAt": started,
                "status": "completed",
            }
        ],
        "url": f"{RUN}/job/{database_id}",
    }


JOBS: dict[str, Any] = {
    "jobs": [
        job(
            "What does it need?",
            "success",
            124479654360,
            "2026-10-31T07:40:01Z",
            "2026-10-31T07:40:08Z",
        ),
        job(
            "install (ubuntu-latest, Python 3.12)",
            "success",
            124479681699,
            "2026-10-31T07:40:09Z",
            "2026-10-31T07:43:10Z",
        ),
        job(
            "install (windows-latest, Python 3.15)",
            "success",
            124479681805,
            "2026-10-31T07:40:09Z",
            "2026-10-31T07:52:41Z",
        ),
        job(
            "install (macos-latest, Python 3.13)",
            "success",
            124479681743,
            "2026-10-31T07:40:09Z",
            "2026-10-31T07:45:02Z",
        ),
        job(
            "install (windows-latest, Python 3.12)",
            "success",
            124479681847,
            "2026-10-31T07:40:09Z",
            "2026-10-31T07:51:30Z",
        ),
        job("report", "success", 124481487575, "2026-10-31T07:52:45Z", "2026-10-31T07:52:52Z"),
    ]
}


def failing(*legs: tuple[str, str, str]) -> dict[str, Any]:
    """The jobs, with each (runner, python, conclusion) leg concluding as given."""
    jobs = copy.deepcopy(JOBS)
    for runner, python, conclusion in legs:
        [entry] = [j for j in jobs["jobs"] if j["name"] == f"install ({runner}, Python {python})"]
        entry["conclusion"] = conclusion
    return jobs


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


def run_script(tmp_path: Path, jobs: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps(jobs), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "release_check_report.py"), str(path), TAG, RUN, RELEASE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def test_the_script_prints_the_issue_as_json_when_a_leg_failed(tmp_path: Path) -> None:
    done = run_script(tmp_path, failing(("ubuntu-latest", "3.12", "failure")))
    assert done.returncode == 0, done.stderr
    printed = json.loads(done.stdout)
    assert printed == release_check_report.issue(
        [Failed("Linux", "3.12", "failure", f"{RUN}/job/124479681699")], TAG, RUN, RELEASE
    )


def test_the_script_prints_nothing_when_every_leg_passed(tmp_path: Path) -> None:
    done = run_script(tmp_path, JOBS)
    assert (done.returncode, done.stdout) == (0, "")


@pytest.mark.parametrize("argv", [[], ["jobs.json", TAG]])
def test_the_script_refuses_the_wrong_arguments_with_its_usage(argv: list[str]) -> None:
    assert release_check_report.main(argv) == 2
