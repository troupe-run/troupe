"""The release install check workflow checks the bundle's tags, and only they open a Bug (spec:
installation; install-from-tag design D5, D6). Its Python matrix is checked by python_versions.py.

The tag filter is a copy of install_check.TAG_PREFIX, since a workflow can't import it: these tests
keep the two the same."""

from pathlib import Path
from typing import Any

import yaml
from conftest import REPO

import install_check
import python_versions

WORKFLOW = REPO / python_versions.RELEASE_CHECK
TAGGED = f"startsWith(github.event.release.tag_name, '{install_check.TAG_PREFIX}')"


def workflow(path: Path = WORKFLOW) -> dict[Any, Any]:
    loaded: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded


def triggers() -> dict[str, Any]:
    # YAML 1.1 reads the key `on` as True.
    found: dict[str, Any] = workflow()[True]
    return found


def test_it_runs_when_a_release_is_published_and_on_demand_for_a_ref() -> None:
    assert triggers()["release"] == {"types": ["published"]}
    assert triggers()["workflow_dispatch"]["inputs"]["ref"]["required"] is True


def test_the_install_legs_run_only_for_the_bundles_tag_or_on_demand() -> None:
    condition = workflow()["jobs"]["install"]["if"]
    assert condition == f"${{{{ github.event_name == 'workflow_dispatch' || {TAGGED} }}}}"


def test_each_leg_installs_from_github_by_the_ref() -> None:
    [check] = [
        step
        for step in workflow()["jobs"]["install"]["steps"]
        if "install_check.py" in step.get("run", "")
    ]
    assert (
        check["run"] == 'uv run scripts/install_check.py --hosted --ref "$REF" --python "$PYTHON"'
    )
    assert check["env"]["REF"] == "${{ github.event.release.tag_name || inputs.ref }}"


def test_only_a_failure_for_the_bundles_tag_opens_a_bug() -> None:
    report = workflow()["jobs"]["report"]
    assert report["needs"] == "install"
    assert report["if"] == (
        "${{ failure() && startsWith(github.event.release.tag_name || inputs.ref, "
        f"'{install_check.TAG_PREFIX}') }}}}"
    )


def test_only_the_report_job_may_write_and_only_issues() -> None:
    assert workflow()["permissions"] == {"contents": "read"}
    assert workflow()["jobs"]["report"]["permissions"] == {
        "contents": "read",
        "actions": "read",
        "issues": "write",
    }
    assert "permissions" not in workflow()["jobs"]["install"]


def test_no_job_reads_a_secret() -> None:
    assert "secrets." not in WORKFLOW.read_text(encoding="utf-8")


def test_a_failure_while_the_tags_bug_is_open_comments_on_it_instead_of_opening_another() -> None:
    [step] = workflow()["jobs"]["report"]["steps"][1:]
    script = step["run"]
    assert 'export TITLE="Install check failed for $TAG"' in script
    assert "--state open" in script
    assert "select(.title == env.TITLE)" in script
    comment, create = script.index("gh issue comment"), script.index("--method POST")
    assert script.index('if [ -n "$open" ]') < comment < create
