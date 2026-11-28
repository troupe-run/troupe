"""One line per run event in troupe logs (spec: cli, "Status and logs commands"), and a run's
tokens and cost in status and logs (spec: cli, "Status shows a run's tokens and cost" and the
requirements after it; run-usage-display design, the approved look)."""

import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest

from runner_schemas import RUNNER_SCHEMAS, load
from troupe.cli.render import (
    render_error,
    render_event,
    render_log_entry,
    render_logged_notice,
    render_notice,
    render_run,
    render_run_line,
)
from troupe.core.client import messages as m
from troupe.core.errors import TroupeError

AT = "2026-11-07T00:00:00Z"


def _logged(event: dict[str, object]) -> dict[str, object]:
    return {"seq": 1, "at": AT, "event": event}


def test_a_served_model_line_names_the_model() -> None:
    line = render_event(_logged({"type": "served_model", "model": "gpt-6-luna-2026-03-05"}))
    assert line == f"     1 {AT} served_model: gpt-6-luna-2026-03-05"


def test_a_result_line_names_its_reason_and_why_it_wasnt_retried() -> None:
    event: dict[str, object] = {
        "type": "result",
        "status": "error",
        "reason": "network",
        "notRetried": "side-effect",
        "message": "the connection dropped",
    }
    line = render_event(_logged(event))
    assert (
        line
        == f"     1 {AT} result: error (network, not retried: side-effect): the connection dropped"
    )


def test_a_result_line_without_not_retried_names_only_its_reason() -> None:
    event: dict[str, object] = {
        "type": "result",
        "status": "error",
        "reason": "network",
        "message": "gave up",
    }
    assert render_event(_logged(event)) == f"     1 {AT} result: error (network): gave up"


def _host_event_types() -> list[str]:
    defs = load(RUNNER_SCHEMAS / "run-event.schema.json")["$defs"]
    return [ref["$ref"].rsplit("/", 1)[1] for ref in defs["hostEvent"]["oneOf"]]


@pytest.mark.parametrize("type_", _host_event_types())
def test_every_host_event_type_has_a_summary_after_its_type(type_: str) -> None:
    line = render_event(_logged({"type": type_}))
    assert not line.endswith(f"{type_}:"), json.dumps(line)


# A run's tokens and cost (run-usage-display). The expected lines are the ones the owner approved
# on 2026-11-21, in the design.

USAGE = {
    "inputTokens": 1204,
    "outputTokens": 9817,
    "cacheReadTokens": 182330,
    "cacheWriteTokens": 14022,
}
ESTIMATED_USAGE = {
    "inputTokens": 3410,
    "outputTokens": 2066,
    "cacheReadTokens": 21504,
    "cacheWriteTokens": 0,
}
RUN_ID = "0193a4c2-7f1e-7b55-9c1d-2a6f0e3b8d41"
SUMMARY: dict[str, Any] = {
    "runId": RUN_ID,
    "performanceId": "7a1c0d2e-0000-4000-8000-00000000000a",
    "step": 1,
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
    "outcome": "succeeded",
    "events": 42,
    "startedAt": "2026-11-21T09:14:02.000Z",
    "endedAt": "2026-11-21T09:16:40.000Z",
    "transcript": "sha256:" + "a" * 64,
    "transcriptFormat": "native",
    "audit": {"outside": []},
}


def _summary(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    data = {**copy.deepcopy(SUMMARY), **fields}
    m.RunSummary.from_data(data)  # a shape troupe sends
    return data


def _after_events(lines: list[str]) -> list[str]:
    """The lines between a run summary's events line and its audit, which comes next."""
    start = lines.index("  events: 42") + 1
    end = lines.index("  audit: every change the run made was declared")
    return lines[start:end]


def test_status_of_a_run_whose_service_reported_its_cost() -> None:
    lines = render_run(_summary(usage=USAGE, cost={"usd": 0.4213, "kind": "reported"}))
    assert _after_events(lines) == [
        "  tokens: 1,204 input, 9,817 output, 182,330 cache read, 14,022 cache write",
        "  cost: $0.4213, reported by the service",
    ]


def test_status_of_a_run_whose_cost_was_estimated() -> None:
    lines = render_run(_summary(usage=ESTIMATED_USAGE, cost={"usd": 0.0136, "kind": "estimated"}))
    assert _after_events(lines) == [
        "  tokens: 3,410 input, 2,066 output, 21,504 cache read, 0 cache write",
        "  cost: ~$0.0136, estimated from the runtime's price",
    ]


def test_status_of_a_run_whose_runner_reported_neither() -> None:
    lines = render_run(_summary())
    assert _after_events(lines) == []
    assert not any(line.startswith(("  tokens:", "  cost:")) for line in lines)


def test_status_of_a_run_with_tokens_and_no_price() -> None:
    lines = render_run(_summary(usage=ESTIMATED_USAGE))
    assert _after_events(lines) == [
        "  tokens: 3,410 input, 2,066 output, 21,504 cache read, 0 cache write"
    ]


def test_a_counter_the_runner_left_out_is_left_out_of_the_line_never_shown_as_zero() -> None:
    usage = {key: value for key, value in USAGE.items() if key != "cacheWriteTokens"}
    lines = render_run(_summary(usage=usage))
    assert _after_events(lines) == ["  tokens: 1,204 input, 9,817 output, 182,330 cache read"]


@pytest.mark.parametrize(
    ("cost", "shown"),
    [
        (
            {"usd": 0.00003, "kind": "estimated"},
            "~under $0.0001, estimated from the runtime's price",
        ),
        ({"usd": 0.00003, "kind": "reported"}, "under $0.0001, reported by the service"),
        ({"usd": 0, "kind": "reported"}, "$0, reported by the service"),
        ({"usd": 0, "kind": "estimated"}, "~$0, estimated from the runtime's price"),
        ({"usd": 0.123456, "kind": "reported"}, "$0.1235, reported by the service"),
        ({"usd": 0.00005, "kind": "reported"}, "$0.0001, reported by the service"),
        ({"usd": 12.5, "kind": "reported"}, "$12.5000, reported by the service"),
    ],
    ids=[
        "a tiny estimate",
        "a tiny reported cost",
        "zero",
        "a zero estimate",
        "rounding",
        "half rounds up",
        "dollars",
    ],
)
def test_a_cost_is_shown_to_four_places_never_as_a_false_zero(
    cost: dict[str, Any], shown: str
) -> None:
    assert f"  cost: {shown}" in render_run(_summary(cost=cost))


@pytest.mark.parametrize(
    ("fields", "ending"),
    [
        ({"cost": {"usd": 0.4213, "kind": "reported"}}, "  42 events, $0.4213"),
        (
            {"cost": {"usd": 0.0136, "kind": "estimated"}, "events": 17},
            "  17 events, ~$0.0136 estimated",
        ),
        ({"events": 17}, "  17 events"),
        ({"usage": USAGE, "events": 17}, "  17 events"),
    ],
    ids=["reported", "estimated", "neither", "tokens only"],
)
def test_the_list_of_runs_ends_each_line_with_its_cost(fields: dict[str, Any], ending: str) -> None:
    line = render_run_line(_summary(**fields))
    assert line.endswith(ending)
    assert "tokens" not in line


def test_the_list_line_of_a_run_with_notices_and_a_cost() -> None:
    notice = {
        "at": "2026-11-21T09:15:00.000Z",
        "notice": {"code": "run.silent", "problem": "p", "fix": "f"},
    }
    line = render_run_line(
        _summary(notices=[notice, notice], cost={"usd": 0.4213, "kind": "reported"})
    )
    assert line.endswith("42 events, 2 notices, $0.4213")


def _result(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "seq": 41,
        "at": "2026-11-21T09:16:39Z",
        "event": {"type": "result", "status": "ok", **fields},
    }


def test_a_result_line_with_a_reported_cost() -> None:
    line = render_event(_result(message="All 18 tests pass.", usage=USAGE, costUsd=0.4213))
    assert line == (
        "    41 2026-11-21T09:16:39Z result: ok: All 18 tests pass. (tokens 1,204 in, 9,817 out, "
        "182,330 cache read, 14,022 cache write; cost $0.4213, reported)"
    )


def test_a_result_line_with_an_estimated_cost() -> None:
    line = render_event(
        _result(message="Reviewed 3 files.", usage=ESTIMATED_USAGE, estimatedCostUsd=0.0136)
    )
    assert line.endswith(
        "result: ok: Reviewed 3 files. (tokens 3,410 in, 2,066 out, 21,504 cache read, "
        "0 cache write; cost ~$0.0136, estimated)"
    )


def test_a_result_line_with_neither_ends_with_its_message() -> None:
    assert render_event(_result(message="Reviewed 3 files.")).endswith(
        "result: ok: Reviewed 3 files."
    )


def test_a_result_line_with_tokens_and_no_cost() -> None:
    line = render_event(_result(message="m", usage={"inputTokens": 3, "outputTokens": 4}))
    assert line.endswith("result: ok: m (tokens 3 in, 4 out)")


def test_a_result_line_with_a_cost_and_no_tokens() -> None:
    line = render_event(_result(message="m", estimatedCostUsd=0.00003))
    assert line.endswith("result: ok: m (cost ~under $0.0001, estimated)")


def test_a_failed_result_line_keeps_its_reason_before_the_figures() -> None:
    line = render_event(
        _result(status="error", reason="budget", message="spent", usage={"outputTokens": 9000})
    )
    assert line.endswith("result: error (budget): spent (tokens 9,000 out)")


# Each event type's line in troupe logs, from an entry of the shape a run's log really holds.

LOG_RUN = "0193a4c2-7f1e-7b55-9c1d-2a6f0e3b8d41"
LOG_AT = "2026-11-21T09:15:00.000Z"


def _entry(seq: int, **event: Any) -> dict[str, Any]:  # noqa: ANN401
    entry = {
        "kind": "event",
        "runId": LOG_RUN,
        "seq": seq,
        "at": LOG_AT,
        "event": {"runId": LOG_RUN, "seq": seq, **event},
    }
    m.LoggedEvent.from_data(entry)  # a shape troupe sends
    return entry


def _summary_of(seq: int, **event: Any) -> str:  # noqa: ANN401
    """The line's text after its type, which the seq and time come before."""
    line = render_event(_entry(seq, **event))
    prefix = f"  {seq:>4} {LOG_AT} {event['type']}: "
    assert line.startswith(prefix), line
    return line.removeprefix(prefix)


def test_an_event_line_right_aligns_its_seq_in_four_places() -> None:
    entry = _entry(12345, type="log", level="info", message="m")
    assert render_event(entry) == f"  12345 {LOG_AT} log: info: m"
    entry = _entry(7, type="log", level="info", message="m")
    assert render_event(entry) == f"     7 {LOG_AT} log: info: m"


def test_an_init_line_names_the_runner_and_its_version() -> None:
    init = {
        "runner": {"name": "fake-runner", "version": "1.2.3"},
        "tools": [],
        "effects": "checked",
    }
    assert _summary_of(0, type="init", **init) == "fake-runner 1.2.3"


def test_a_turn_line_names_the_role_and_the_first_line_of_its_text() -> None:
    text = "  First line.  \nSecond line."
    assert _summary_of(1, type="turn", role="assistant", text=text) == "assistant: First line."


def test_a_turn_line_with_no_text_ends_at_its_role() -> None:
    assert render_event(_entry(1, type="turn", role="user", text=" \n ")).endswith("turn: user:")


@pytest.mark.parametrize(
    ("length", "shown"),
    [(100, "a" * 100), (101, "a" * 99 + "…"), (150, "a" * 99 + "…")],
    ids=["exactly the limit", "one over", "well over"],
)
def test_a_line_longer_than_100_characters_is_cut_to_100_with_an_ellipsis(
    length: int, shown: str
) -> None:
    assert _summary_of(1, type="turn", role="user", text="a" * length) == f"user: {shown}"


def test_a_tool_call_line_names_the_tool_and_its_input() -> None:
    call = {"callId": "c1", "tool": "Bash", "inputSummary": "ls -la\nmore"}
    assert _summary_of(2, type="tool_call", **call) == "Bash ls -la"


@pytest.mark.parametrize(("is_error", "word"), [(False, "ok"), (True, "error")])
def test_a_tool_result_line_says_ok_or_error_then_its_output(is_error: bool, word: str) -> None:
    result = {"callId": "c1", "isError": is_error, "outputSummary": "done\nrest", "outputBytes": 9}
    assert _summary_of(3, type="tool_result", **result) == f"{word} done"


def test_a_retry_line_names_the_attempt_and_the_reason() -> None:
    retry = {"attempt": 2, "delayMs": 500, "reason": "rate-limit"}
    assert _summary_of(4, type="retry", **retry) == "attempt 2, rate-limit"


def test_a_log_line_names_its_level_and_message() -> None:
    assert _summary_of(5, type="log", level="warning", message="slow\nmore") == "warning: slow"


def test_an_oversized_line_names_the_type_size_and_where_it_is_kept() -> None:
    ref = "sha256:" + "b" * 64
    oversized = {"originalType": "tool_result", "bytes": 2_000_000, "ref": ref}
    assert _summary_of(6, type="oversized", **oversized) == f"tool_result, 2000000 bytes, {ref}"


@pytest.mark.parametrize(
    ("counts", "shown"),
    [
        ({}, ""),
        ({"tokensBefore": 41000, "tokensAfter": 9000}, ", tokens 41000 → 9000"),
        ({"tokensBefore": 41000}, ", tokens 41000 → ?"),
        ({"messagesAfter": 3}, ", messages ? → 3"),
        (
            {"tokensBefore": 5, "tokensAfter": 2, "messagesBefore": 40, "messagesAfter": 4},
            ", tokens 5 → 2, messages 40 → 4",
        ),
    ],
    ids=["no counts", "tokens", "tokens before only", "messages after only", "both"],
)
def test_a_context_line_names_kind_and_by_with_each_count_it_carries(
    counts: dict[str, int], shown: str
) -> None:
    context = {"kind": "compacted", "by": "engine", "message": "squeezed\nmore", **counts}
    assert _summary_of(7, type="context", **context) == f"compacted by engine{shown}: squeezed"


def test_a_result_line_with_neither_reason_nor_figures_is_status_and_message() -> None:
    assert _summary_of(9, type="result", status="ok", message="All done.\nmore") == "ok: All done."


def test_a_line_for_an_event_type_troupe_does_not_know_is_its_type_alone() -> None:
    logged = {"seq": 3, "at": LOG_AT, "event": {"type": "future"}}
    assert render_event(logged) == f"     3 {LOG_AT} future:"


# A notice a run recorded, among its events.


def _logged_notice(problem: str) -> dict[str, Any]:
    entry = {
        "kind": "run-notice",
        "runId": LOG_RUN,
        "at": LOG_AT,
        "notice": {"code": "run.silent", "problem": problem, "fix": "wait"},
    }
    m.LoggedNotice.from_data(entry)  # a shape troupe sends
    return entry


def test_a_recorded_notice_line_has_a_blank_seq_then_its_code_and_problem() -> None:
    line = render_logged_notice(_logged_notice("It went quiet.\nFor a while."))
    assert line == f"       {LOG_AT} notice run.silent: It went quiet."


def test_a_log_entry_is_shown_as_a_notice_or_an_event_by_its_kind() -> None:
    notice = _logged_notice("quiet")
    assert render_log_entry(notice) == render_logged_notice(notice)
    event = _entry(5, type="log", level="info", message="hello")
    assert render_log_entry(event) == f"     5 {LOG_AT} log: info: hello"


# An error and a notice, as written to standard error.

ELSEWHERE = Path.home() / "projects" / "app" / "troupe.toml"
SHOWN = f"~{os.sep}projects{os.sep}app{os.sep}troupe.toml"


def test_an_error_is_its_problem_then_its_path_then_its_fix() -> None:
    error = TroupeError("usage.invalid", "Nothing to do.", "Name a run.", path=str(ELSEWHERE))
    assert render_error(error) == (f"troupe: Nothing to do.\n  path: {SHOWN}\n  fix: Name a run.")


def test_an_error_with_no_path_has_no_path_line() -> None:
    error = TroupeError("usage.invalid", "Nothing to do.", "Name a run.")
    assert render_error(error) == "troupe: Nothing to do.\n  fix: Name a run."


def test_a_notice_is_its_problem_then_its_path_then_its_fix() -> None:
    notice = {"code": "run.silent", "problem": "Quiet.", "fix": "Wait.", "path": str(ELSEWHERE)}
    assert render_notice(notice) == f"troupe: Quiet.\n  path: {SHOWN}\n  fix: Wait."


def test_a_notice_with_no_path_has_no_path_line() -> None:
    notice = {"code": "run.silent", "problem": "Quiet.", "fix": "Wait."}
    assert render_notice(notice) == "troupe: Quiet.\n  fix: Wait."
