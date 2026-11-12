"""The capture tool refuses a context-limit fixture whose run compacted (spec: claude-code-runner,
"A context-limit fixture is captured with compaction off"; compaction-off design D3)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "capture_claude.py"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "claude-code"
EXPECTED_REQUESTS = {"context-limit-refused": 2, "context-limit-blocked": 1}

COMPACTING = '{"type":"system","subtype":"status","status":"compacting","compact_output_chars":0}'
COMPACT_FAILED = (
    '{"type":"system","subtype":"status","status":null,"compact_result":"failed",'
    '"compact_error":"exhausted"}'
)
"""The two records Claude Code 2.1.319 wrote under -p when compaction was on and the stand-in
refused the compaction request (the design's probe)."""
COMPACT_BOUNDARY = '{"type":"system","subtype":"compact_boundary"}'


def _tool() -> ModuleType:
    """The capture tool, a script rather than a package module, loaded from its path."""
    spec = importlib.util.spec_from_file_location("capture_claude", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _native_lines(fixture: str) -> list[str]:
    entries = (FIXTURES / fixture / "recording.jsonl").read_text(encoding="utf-8").splitlines()
    return [entry["transcript"] for line in entries if "transcript" in (entry := json.loads(line))]


@pytest.mark.parametrize("fixture", sorted(EXPECTED_REQUESTS))
def test_a_committed_context_limit_recording_with_its_request_count_may_be_written(
    fixture: str,
) -> None:
    lines = _native_lines(fixture)
    assert _tool().context_limit_refusal(fixture, lines, EXPECTED_REQUESTS[fixture]) is None


@pytest.mark.parametrize("fixture", sorted(EXPECTED_REQUESTS))
@pytest.mark.parametrize("compaction", [COMPACTING, COMPACT_FAILED, COMPACT_BOUNDARY])
def test_a_recording_that_reports_compacting_is_refused(fixture: str, compaction: str) -> None:
    lines = _native_lines(fixture)
    lines.insert(-2, compaction)
    refusal = _tool().context_limit_refusal(fixture, lines, EXPECTED_REQUESTS[fixture])
    assert refusal is not None
    assert "compaction wasn't off" in refusal


@pytest.mark.parametrize("fixture", sorted(EXPECTED_REQUESTS))
@pytest.mark.parametrize("extra", [-1, 1])
def test_a_request_count_other_than_the_cases_is_refused(fixture: str, extra: int) -> None:
    lines = _native_lines(fixture)
    refusal = _tool().context_limit_refusal(fixture, lines, EXPECTED_REQUESTS[fixture] + extra)
    assert refusal is not None
    assert "compaction wasn't off" in refusal


@pytest.mark.parametrize("fixture", sorted(EXPECTED_REQUESTS))
def test_a_run_that_ended_for_another_reason_is_refused(fixture: str) -> None:
    lines = _native_lines(fixture)
    result = json.loads(lines[-1])
    result["terminal_reason"] = "budget_exhausted"
    lines[-1] = json.dumps(result)
    refusal = _tool().context_limit_refusal(fixture, lines, EXPECTED_REQUESTS[fixture])
    assert refusal is not None
    assert "didn't end at the context limit" in refusal


def test_a_line_that_isnt_json_is_neither_compaction_nor_a_refusal() -> None:
    lines = ["Update available", *_native_lines("context-limit-refused")]
    assert _tool().compaction_seen(lines) == []
    assert _tool().context_limit_refusal("context-limit-refused", lines, 2) is None
