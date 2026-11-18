"""dependency-report.yml audits the lock file weekly and keeps one issue, and only its board job
holds the board App's key (spec: quality-check, "Advisories no gate blocks on are reported weekly";
quality-gates design D4)."""

from typing import Any

import yaml
from conftest import REPO

WORKFLOW = REPO / ".github" / "workflows" / "dependency-report.yml"


def workflow() -> dict[Any, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def triggers() -> dict[str, Any]:
    # YAML 1.1 reads the key `on` as True.
    loaded = workflow()
    value = loaded["on"] if "on" in loaded else loaded[True]
    assert isinstance(value, dict)
    return value


def test_it_runs_every_monday_and_by_hand() -> None:
    assert triggers()["schedule"] == [{"cron": "23 4 * * 1"}]
    assert "workflow_dispatch" in triggers()
    assert set(triggers()) == {"schedule", "workflow_dispatch"}


def test_the_audit_job_can_write_issues_and_nothing_else() -> None:
    assert workflow()["permissions"] == {}
    audit = workflow()["jobs"]["audit"]
    assert audit["permissions"] == {"contents": "read", "issues": "write"}
    assert "environment" not in audit
    report = next(s for s in audit["steps"] if s.get("id") == "report")
    assert report["run"].startswith("uv run scripts/quality_gates.py report ")
    assert '--github-output "$GITHUB_OUTPUT"' in report["run"]
    assert report["env"] == {"GH_TOKEN": "${{ github.token }}"}


def test_only_the_board_job_holds_the_board_apps_key() -> None:
    board = workflow()["jobs"]["board"]
    assert board["environment"]["name"] == "board"
    assert board["permissions"] == {}
    assert board["needs"] == "audit"
    assert "needs.audit.outputs.issue-url != ''" in board["if"]
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("secrets.BOARD_APP_PRIVATE_KEY") == 1


def test_the_board_job_checks_the_url_it_is_handed() -> None:
    run = workflow()["jobs"]["board"]["steps"][-1]["run"]
    assert r"^https://github\.com/troupe-run/troupe/issues/[0-9]+$" in run
    assert run.strip().endswith('gh project item-add 1 --owner troupe-run --url "$ISSUE_URL"')
