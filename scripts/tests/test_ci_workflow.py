"""CI's workflow runs the full check on every merge group, so troupe's merge queue always gets a
`check` to land on (spec: quality-check; ci-on-merge-queue design D1, D2). It runs no legs on a
draft and skips its `check`, runs them once the draft is marked ready, and asks the merge queue
before running them again on main (ci-once-per-commit design D1 to D4). These tests read the
workflow's structure, and each fails naming what would skip or narrow the check on the queue, or
let a draft's `check` narrow a later push. Every leg also runs the documented install after a full
check (spec: installation; install-with-uv design D5). The broken copies at the end show each one
can fail."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import REPO

CI = ".github/workflows/ci.yml"
CHANGES = "changes"
"""The job that answers what a pull request or a push to main needs, and so the only one that may
narrow."""
NOT_A_MERGE_GROUP = "github.event_name != 'merge_group'"

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
            if condition != NOT_A_MERGE_GROUP:
                found.append(
                    f"{CI}'s `{CHANGES}` job runs on `if: {condition}`: keep `if: "
                    f"{NOT_A_MERGE_GROUP}`, so a merge group gets no answer and runs the full "
                    "check, and a draft and a push to main still get one."
                )
        elif "github.event_name" in condition:
            found.append(
                f"{CI}'s `{name}` job reads the event in `if: {condition}`: only `{CHANGES}` may, "
                "or a merge group could skip a leg or `check`."
            )
    return found


PULL_REQUEST_TYPES = ["opened", "synchronize", "reopened", "ready_for_review"]


def pull_request_type_problems(workflow: dict[Any, Any]) -> list[str]:
    on = triggers(workflow).get("pull_request") or {}
    types = on.get("types") if isinstance(on, dict) else None
    if types == PULL_REQUEST_TYPES:
        return []
    return [
        f"{CI}'s `pull_request` types are {types}: keep {PULL_REQUEST_TYPES}. Naming a type "
        "replaces GitHub's defaults, and `ready_for_review` runs what a draft skipped."
    ]


def changes_step(workflow: dict[Any, Any], step_id: str) -> dict[Any, Any] | None:
    steps = workflow["jobs"][CHANGES]["steps"]
    return next((step for step in steps if step.get("id") == step_id), None)


DRAFT_CONDITION = "github.event_name == 'pull_request' && github.event.pull_request.draft"
DRAFT_ANSWERS = ("scope=none", "draft=true")


def draft_step_problems(workflow: dict[Any, Any]) -> list[str]:
    step = changes_step(workflow, "draft")
    if step is None:
        return [
            f"{CI}'s `{CHANGES}` job has no step with `id: draft`: a draft would run every leg "
            "before its review is clean."
        ]
    problems: list[str] = []
    if step.get("if") != DRAFT_CONDITION:
        problems.append(
            f"{CI}'s draft step runs on `if: {step.get('if')}`: keep `if: {DRAFT_CONDITION}`."
        )
    missing = [answer for answer in DRAFT_ANSWERS if answer not in str(step.get("run", ""))]
    if missing:
        problems.append(
            f"{CI}'s draft step doesn't answer {', '.join(missing)}: a draft must skip the legs, "
            "and `check` (ci-once-per-commit design D3)."
        )
    return problems


QUEUE_PASSED = "scripts/queue_passed.py"


def push_step_problems(workflow: dict[Any, Any]) -> list[str]:
    step = changes_step(workflow, "main")
    if step is None or QUEUE_PASSED not in str(step.get("run", "")):
        return [
            f"{CI}'s `{CHANGES}` job has no `id: main` step running {QUEUE_PASSED}: a push to main "
            "would get no answer and rerun the commit the merge queue passed."
        ]
    problems: list[str] = []
    if step.get("if") != "github.event_name == 'push'":
        problems.append(
            f"{CI}'s push step runs on `if: {step.get('if')}`: keep `if: github.event_name == "
            "'push'`."
        )
    if (step.get("env") or {}).get("SHA") != "${{ github.sha }}" or '--sha "$SHA"' not in str(
        step["run"]
    ):
        problems.append(
            f"{CI}'s push step doesn't pass `--sha` the pushed commit (`github.sha`): it must ask "
            "about the commit that landed."
        )
    return problems


CHECK_CONDITION = "${{ always() && needs.changes.outputs.draft != 'true' }}"


def check_condition_problems(workflow: dict[Any, Any]) -> list[str]:
    condition = workflow["jobs"]["check"].get("if")
    outputs = workflow["jobs"][CHANGES].get("outputs") or {}
    problems: list[str] = []
    if condition != CHECK_CONDITION:
        problems.append(
            f"{CI}'s `check` runs on `if: {condition}`: keep `if: {CHECK_CONDITION}`, so a draft's "
            "`check` is skipped and can never read as passed (ci-once-per-commit design D3)."
        )
    if outputs.get("draft") != "${{ steps.draft.outputs.draft }}":
        problems.append(
            f"{CI}'s `{CHANGES}` doesn't output `draft` from its draft step: `check` reads it."
        )
    return problems


LOOKUP = "check-runs?check_name=check&app_id=15368&filter=all"


def lookup_problems(workflow: dict[Any, Any]) -> list[str]:
    step = changes_step(workflow, "paths")
    if step is not None and LOOKUP in str(step.get("run", "")):
        return []
    return [
        f"{CI}'s paths step doesn't look up `{LOOKUP}`: with the default filter the API lists "
        "one `check` per workflow run in no promised order, so check_range.py must see them all "
        "and judge the latest (ci-once-per-commit design D3)."
    ]


@pytest.mark.parametrize(
    "check",
    [
        pull_request_type_problems,
        draft_step_problems,
        push_step_problems,
        check_condition_problems,
        lookup_problems,
    ],
)
def test_drafts_wait_for_ready_and_main_asks_the_merge_queue(check: Check) -> None:
    assert check(load(REPO / CI)) == []


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
            f"    if: {NOT_A_MERGE_GROUP}\n",
            "    if: ${{ always() }}\n",
            event_condition_problems,
            "`changes` job runs on",
            id="changes widened to merge groups",
        ),
        pytest.param(
            f"    if: {NOT_A_MERGE_GROUP}\n",
            "    if: github.event_name == 'pull_request'\n",
            event_condition_problems,
            "`changes` job runs on",
            id="changes confined to pull requests again",
        ),
        pytest.param(
            "    types: [opened, synchronize, reopened, ready_for_review]\n",
            "    types: [opened, synchronize, reopened]\n",
            pull_request_type_problems,
            "keep ['opened', 'synchronize', 'reopened', 'ready_for_review']",
            id="ready_for_review dropped",
        ),
        pytest.param(
            "        id: draft\n",
            "        id: drafts\n",
            draft_step_problems,
            "no step with `id: draft`",
            id="draft step removed",
        ),
        pytest.param(
            "scope=none\\ncheck-args=\\ndraft=true",
            "scope=none\\ncheck-args=",
            draft_step_problems,
            "doesn't answer draft=true",
            id="draft step without its draft answer",
        ),
        pytest.param(
            f"python3 {QUEUE_PASSED}",
            "true",
            push_step_problems,
            f"running {QUEUE_PASSED}",
            id="push step without the merge-queue lookup",
        ),
        pytest.param(
            "          SHA: ${{ github.sha }}\n",
            "          SHA: ${{ github.event.before }}\n",
            push_step_problems,
            "the pushed commit",
            id="push step asks about the wrong commit",
        ),
        pytest.param(
            f"    if: {CHECK_CONDITION}\n",
            "    if: ${{ always() }}\n",
            check_condition_problems,
            "a draft's `check` is skipped",
            id="check runs on drafts",
        ),
        pytest.param(
            "&filter=all",
            "",
            lookup_problems,
            "judge the latest",
            id="lookup back to the default filter",
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
