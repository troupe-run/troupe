"""CI's workflow runs the full check on every merge group, so troupe's merge queue always gets a
`check` to land on (spec: quality-check; ci-on-merge-queue design D1, D2). These tests read the
workflow's structure, and each fails naming what would skip or narrow the check on the queue. Every
leg also runs the documented install after a full check (spec: installation; install-with-uv design
D5). The broken copies at the end show each one can fail."""

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


INSTALL_CHECK = "scripts/install_check.py"
INSTALL_CONDITION = "${{ needs.changes.outputs['check-args'] == '' }}"
INSTALL_ARGUMENTS = ("--ref ${{ github.sha }}", "--python ${{ matrix.python }}")


def install_step_problems(workflow: dict[Any, Any]) -> list[str]:
    # spec: installation, "The documented install is checked on every platform" (design D5).
    steps = workflow["jobs"]["check-legs"]["steps"]
    found = [step for step in steps if INSTALL_CHECK in str(step.get("run", ""))]
    if not found:
        return [
            f"{CI}'s `check-legs` doesn't run {INSTALL_CHECK}: keep its install-check step, so the "
            "documented install is checked on every platform and Python."
        ]
    problems: list[str] = []
    for step in found:
        condition = str(step.get("if", ""))
        if condition != INSTALL_CONDITION:
            problems.append(
                f"{CI}'s install-check step runs on `if: {condition}`: keep `if: "
                f"{INSTALL_CONDITION}`, so it runs after every full check and no scoped one."
            )
        missing = [argument for argument in INSTALL_ARGUMENTS if argument not in step["run"]]
        if missing:
            problems.append(
                f"{CI}'s install-check step doesn't pass {', '.join(missing)}: it must install the "
                "commit under test, on the leg's Python."
            )
    return problems


def test_every_check_leg_installs_the_commit_under_test_after_a_full_check() -> None:
    assert install_step_problems(load(REPO / CI)) == []


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
        pytest.param(
            f"        run: uv run {INSTALL_CHECK} --ref ${{{{ github.sha }}}} --python "
            "${{ matrix.python }}\n",
            "        run: echo skipped\n",
            install_step_problems,
            f"`check-legs` doesn't run {INSTALL_CHECK}",
            id="install check removed",
        ),
        pytest.param(
            f"        if: {INSTALL_CONDITION}\n",
            "        if: ${{ always() }}\n",
            install_step_problems,
            "install-check step runs on `if: ${{ always() }}`",
            id="install check on scoped runs",
        ),
        pytest.param(
            " --ref ${{ github.sha }}",
            "",
            install_step_problems,
            "doesn't pass --ref ${{ github.sha }}",
            id="install check of HEAD rather than the commit under test",
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
