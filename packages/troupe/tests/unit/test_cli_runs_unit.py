"""troupe perform, status and logs on the command line (spec: cli; perform-status-logs design D3,
D4, D14).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_cli_runs.py."""

from pathlib import Path
from typing import Any

import pytest

from cli_runs_shared import cli
from troupe.cli.render import render_event, render_run
from troupe.core.client import messages as m

ALLOWANCE = {"setting": "allow_unenforced_local_stage", "source": "env"}


def test_with_no_theatre_perform_fails_naming_the_directory_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    monkeypatch.chdir(nowhere)
    code, out, err = cli("perform", "tester")
    assert code == 1
    assert out == ""
    assert "no .troupe directory" in err
    assert list(nowhere.iterdir()) == []


def test_a_running_runs_summary_renders_no_outcome_end_transcript_or_stderr() -> None:
    summary = m.RunSummary.from_data(
        {
            "runId": "0f8fad5b-d9cb-469f-a165-70867728950e",
            "actor": "tester",
            "startedBy": {"kind": "human", "id": "ada@example.com", "source": "env"},
            "runner": {"requested": "scripted"},
            "stage": {"name": "local", "effects": "unenforced", "allowedBy": ALLOWANCE},
            "effectCheck": {"kind": "none"},
            "workspace": {"kind": "theatre"},
            "state": "running",
            "events": 0,
            "startedAt": "2026-10-13T00:00:00.000Z",
        }
    )
    lines = render_run(summary.to_data())
    assert "  runner: scripted" in lines
    assert "  outcome: -" in lines
    assert not [line for line in lines if line.startswith(("  ended", "  transcript", "  stderr"))]


@pytest.mark.parametrize(("format_", "shown"), [("native", ""), ("kinds", " (kinds)")])
def test_an_ended_runs_transcript_line_names_kinds_only_when_its_records_have_them(
    format_: str, shown: str
) -> None:
    summary = m.RunSummary.from_data(
        {
            "runId": "0f8fad5b-d9cb-469f-a165-70867728950e",
            "actor": "tester",
            "startedBy": {"kind": "human", "id": "ada@example.com", "source": "env"},
            "runner": {"requested": "scripted"},
            "stage": {"name": "local", "effects": "unenforced", "allowedBy": ALLOWANCE},
            "effectCheck": {"kind": "none"},
            "workspace": {"kind": "theatre"},
            "state": "ended",
            "outcome": "succeeded",
            "events": 2,
            "startedAt": "2026-10-13T00:00:00.000Z",
            "endedAt": "2026-10-13T00:00:01.000Z",
            "transcript": "sha256:" + "a" * 64,
            "transcriptFormat": format_,
            "stderr": "sha256:" + "b" * 64,
            "audit": {"outside": []},
        }
    )
    assert f"  transcript: sha256:{'a' * 64}{shown}" in render_run(summary.to_data())


def _logged(event: dict[str, Any]) -> dict[str, Any]:
    return {"seq": 1, "at": "2026-10-13T00:00:00.000Z", "event": event}


def test_a_context_line_names_kind_who_and_counts_with_a_question_mark_for_a_missing_side() -> None:
    compacted = {"type": "context", "kind": "compacted", "by": "engine", "message": "squashed"}
    assert render_event(_logged({**compacted, "tokensBefore": 41000})) == (
        "     1 2026-10-13T00:00:00.000Z context: compacted by engine, tokens 41000 → ?: squashed"
    )
    truncated = {
        "type": "context",
        "kind": "truncated",
        "by": "runner",
        "message": "dropped old tool output\nand more",
        "messagesBefore": 120,
        "messagesAfter": 34,
    }
    assert render_event(_logged(truncated)) == (
        "     1 2026-10-13T00:00:00.000Z context: truncated by runner, messages 120 → 34: "
        "dropped old tool output"
    )


def test_an_audit_that_couldnt_run_is_shown_with_its_error() -> None:
    summary = {
        "runId": "0f8fad5b-d9cb-469f-a165-70867728950e",
        "actor": "tester",
        "startedBy": {"kind": "unknown"},
        "runner": {"requested": "scripted"},
        "stage": {
            "name": "local",
            "effects": "unenforced",
            "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"},
        },
        "effectCheck": {"kind": "none"},
        "workspace": {"kind": "theatre"},
        "state": "ended",
        "outcome": "cancelled",
        "events": 1,
        "startedAt": "2026-10-13T00:00:00.000Z",
        "endedAt": "2026-10-13T00:00:01.000Z",
        "transcript": "sha256:" + "a" * 64,
        "transcriptFormat": "native",
        "stderr": "sha256:" + "b" * 64,
        "audit": {"error": {"code": "vcs.failed", "problem": "git failed.", "fix": "Look."}},
    }
    m.RunSummary.from_data(summary)  # a shape troupe sends
    lines = render_run(summary)
    assert "  audit couldn't run: vcs.failed: git failed." in lines
