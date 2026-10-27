"""CI's workflow runs the full check on every merge group, so troupe's merge queue always gets a
`check` to land on (spec: quality-check; ci-on-merge-queue design D1, D2). These tests read the
workflow's structure, and each fails naming what would skip or narrow the check on the queue. The
broken copies at the end show each one can fail."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import REPO

CI = ".github/workflows/ci.yml"
CHANGES = "changes"
"""The job that works out a pull request's changed paths, and so the only one that may narrow."""
PULL_REQUEST_ONLY = "github.event_name == 'pull_request'"

Check = Callable[[dict[Any, Any]], list[str]]
"""One of the checks below: the workflow's problems, each naming what to keep."""


def load(path: Path) -> dict[Any, Any]:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), f"{path} isn't a YAML mapping"
    return workflow


def triggers(workflow: dict[Any, Any]) -> dict[Any, Any]:
    # PyYAML reads YAML 1.1, where the bare key `on` is the boolean true.
    on = workflow[True]
    assert isinstance(on, dict), f"{CI}'s `on` isn't a mapping of triggers"
    return on


def merge_group_problems(workflow: dict[Any, Any]) -> list[str]:
    if "merge_group" in triggers(workflow):
        return []
    return [
        f"{CI} doesn't run on `merge_group`: the merge queue would wait on `check` until it timed "
        "out. Keep `merge_group:` in `on`."
    ]


def path_filter_problems(workflow: dict[Any, Any]) -> list[str]:
    return [
        f"{CI}'s `{event}` trigger filters by `{key}`: a required check skipped by a path filter "
        "never reports, and the merge queue waits on it. Remove the filter; `changes` narrows "
        "pull requests instead."
        for event, filters in triggers(workflow).items()
        for key in ("paths", "paths-ignore")
        if isinstance(filters, dict) and key in filters
    ]


def event_condition_problems(workflow: dict[Any, Any]) -> list[str]:
    found: list[str] = []
    for name, job in workflow["jobs"].items():
        condition = str(job.get("if", ""))
        if name == CHANGES:
            if condition != PULL_REQUEST_ONLY:
                found.append(
                    f"{CI}'s `{CHANGES}` job runs on `if: {condition}`: keep `if: "
                    f"{PULL_REQUEST_ONLY}`, so a merge group and a push to main get no answer and "
                    "run the full check."
                )
        elif "github.event_name" in condition:
            found.append(
                f"{CI}'s `{name}` job reads the event in `if: {condition}`: only `{CHANGES}` may, "
                "or a merge group could skip a leg or `check`."
            )
    return found


def test_ci_runs_on_merge_groups() -> None:
    assert merge_group_problems(load(REPO / CI)) == []


def test_no_trigger_filters_by_path() -> None:
    assert path_filter_problems(load(REPO / CI)) == []


def test_only_the_changes_job_reads_the_event_and_only_on_pull_requests() -> None:
    assert event_condition_problems(load(REPO / CI)) == []


LEGS_CONDITION = "    if: ${{ !cancelled() && needs.changes.outputs.scope != 'none' }}\n"


@pytest.mark.parametrize(
    ("before", "after", "check", "expected"),
    [
        pytest.param(
            "  merge_group:\n",
            "",
            merge_group_problems,
            "doesn't run on `merge_group`",
            id="merge_group removed",
        ),
        pytest.param(
            "  pull_request:\n",
            "  pull_request:\n    paths: ['src/**']\n",
            path_filter_problems,
            "`pull_request` trigger filters by `paths`",
            id="path filter on pull_request",
        ),
        pytest.param(
            f"    if: {PULL_REQUEST_ONLY}\n",
            "    if: github.event_name == 'pull_request' || github.event_name == 'merge_group'\n",
            event_condition_problems,
            "`changes` job runs on",
            id="changes widened to merge groups",
        ),
        pytest.param(
            LEGS_CONDITION,
            LEGS_CONDITION.replace("${{ ", "${{ github.event_name != 'merge_group' && "),
            event_condition_problems,
            "`check-legs` job reads the event",
            id="legs skip merge groups",
        ),
    ],
)
def test_a_broken_copy_of_the_workflow_is_named(
    tmp_path: Path, before: str, after: str, check: Check, expected: str
) -> None:
    text = (REPO / CI).read_text(encoding="utf-8")
    assert text.count(before) == 1, f"{CI} no longer holds exactly one {before!r}: update the case"
    broken = tmp_path / "ci.yml"
    broken.write_text(text.replace(before, after), encoding="utf-8")
    [problem] = check(load(broken))
    assert expected in problem
