"""The capture tool refuses a context-limit fixture whose run compacted (spec: claude-code-runner,
"A context-limit fixture is captured with compaction off"; compaction-off design D3), and a
compaction fixture whose run didn't (compaction-opt-in design D10).

Its tests that start a process, open a socket or use a git theatre are in
integration/test_claude_code_capture_integration.py."""

import json
from pathlib import Path

import pytest

from claude_code_capture_shared import _tool

TESTS_ROOT = next(p for p in Path(__file__).resolve().parents if p.name == "tests")
"""This suite's tests directory, found by name so the file can sit at any depth under it."""

FIXTURES = TESTS_ROOT.parent / "fixtures" / "claude-code"
EXPECTED_REQUESTS = {"context-limit-refused": 2, "context-limit-blocked": 1}

COMPACTING = '{"type":"system","subtype":"status","status":"compacting","compact_output_chars":0}'
COMPACT_FAILED = (
    '{"type":"system","subtype":"status","status":null,"compact_result":"failed",'
    '"compact_error":"exhausted"}'
)
"""The two records Claude Code 2.1.319 wrote under -p when compaction was on and the stand-in
refused the compaction request (the design's probe)."""
COMPACT_BOUNDARY = '{"type":"system","subtype":"compact_boundary"}'


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


# Requirement: The capture tool records compaction fixtures only when Claude Code compacted
# (compaction-opt-in design D10)

INIT = '{"type":"system","subtype":"init"}'
REFUSALS = {"compaction-proactive": 0, "compaction-reactive": 1}
FINISHED = '{"type":"result","subtype":"success","is_error":false,"result":"done"}'


@pytest.mark.parametrize("fixture", ["compaction-proactive", "compaction-reactive"])
def test_a_compaction_capture_with_a_boundary_one_compaction_request_and_a_finish_may_be_written(
    fixture: str,
) -> None:
    lines = [INIT, COMPACTING, COMPACT_BOUNDARY, FINISHED]
    assert _tool().compaction_refusal(fixture, lines, 1, REFUSALS[fixture]) is None


@pytest.mark.parametrize("compactions", [0, 2])
def test_a_compaction_capture_without_exactly_one_compaction_request_is_refused(
    compactions: int,
) -> None:
    lines = [INIT, COMPACTING, COMPACT_BOUNDARY, FINISHED]
    refusal = _tool().compaction_refusal("compaction-proactive", lines, compactions, 0)
    assert refusal is not None
    assert "compaction wasn't seen" in refusal


def test_a_compaction_capture_without_a_boundary_is_refused_and_says_so() -> None:
    refusal = _tool().compaction_refusal(
        "compaction-reactive", [INIT, COMPACTING, COMPACT_FAILED, FINISHED], 1, 1
    )
    assert refusal is not None
    assert "wrote 0 compact_boundary records" in refusal


def test_a_compaction_capture_whose_run_didnt_finish_is_refused() -> None:
    failed = FINISHED.replace('"is_error":false', '"is_error":true')
    refusal = _tool().compaction_refusal(
        "compaction-proactive", [INIT, COMPACT_BOUNDARY, failed], 1, 0
    )
    assert refusal is not None
    assert "didn't finish" in refusal


@pytest.mark.parametrize(
    ("content", "recognised"),
    [
        (
            [
                {"type": "tool_result", "tool_use_id": "t", "content": "1\thi"},
                {
                    "type": "text",
                    "text": "Your task is to create a detailed summary of the "
                    "conversation so far, paying close attention to the user's explicit requests.",
                },
            ],
            True,
        ),
        ("Read notes.txt, then reply with one word: done.", False),
        (
            "This session is being continued from a previous conversation. The summary below "
            "covers the earlier portion of the conversation.",
            False,
        ),
        ([{"type": "tool_result", "tool_use_id": "t", "content": "hi"}], False),
    ],
)
def test_a_compaction_request_is_one_whose_last_user_message_asks_for_a_summary(
    content: object, recognised: bool
) -> None:
    # Claude Code 2.1.319 puts a system message after the last user message.
    body = {
        "messages": [
            {"role": "user", "content": content},
            {"role": "system", "content": "<total_tokens>1 tokens left</total_tokens>"},
        ]
    }
    assert _tool().is_compaction_request(body) is recognised


@pytest.mark.parametrize(
    ("fixture", "refusals"), [("compaction-reactive", 0), ("compaction-proactive", 1)]
)
def test_a_compaction_capture_whose_refusals_dont_match_its_fixture_is_refused(
    fixture: str, refusals: int
) -> None:
    lines = [INIT, COMPACTING, COMPACT_BOUNDARY, FINISHED]
    refusal = _tool().compaction_refusal(fixture, lines, 1, refusals)
    assert refusal is not None
    assert f"refused {refusals} requests as too long" in refusal
