"""Claude Code's stream-json mapped onto run events (spec: claude-code-runner; design D5)."""

import json
from typing import Any

import pytest

from claude_harness import FIXTURES, recording
from troupe_runner_claude_code.mapping import Event, Mapper, Out, Transcript, cut, event_size

NAMES = sorted(path.name for path in FIXTURES.iterdir() if path.is_dir())
FIXTURE_RUNNER_VERSION = "unreleased"
"""The runner version the fixtures' hand-written init events name."""
LIMIT = 65536


def _expected(name: str) -> list[Out]:
    out: list[Out] = []
    for line in recording(name):
        if "transcript" in line:
            out.append(Transcript(line["transcript"]))
        else:
            event = {k: v for k, v in line["event"].items() if k not in ("runId", "seq")}
            out.append(Event(event))
    return out


def _feed(*records: object, mapper: Mapper | None = None) -> list[dict[str, Any]]:
    """The events (not transcript records) the records map to, fed as compact JSON lines."""
    mapper = mapper or Mapper("1.0", LIMIT)
    events: list[dict[str, Any]] = []
    for record in records:
        line = record if isinstance(record, bytes) else json.dumps(record).encode()
        events.extend(out.event for out in mapper.feed(line) if isinstance(out, Event))
    return events


INIT = {
    "type": "system",
    "subtype": "init",
    "tools": ["Read"],
    "model": "m",
    "claude_code_version": "9.9.9",
}


def _assistant(*content: dict[str, Any], **extra: object) -> dict[str, Any]:
    return {"type": "assistant", "message": {"content": list(content)}, **extra}


def _tool_use(call_id: str, name: str = "Write", **input_: object) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": input_}


def _tool_result(call_id: str, content: object, **extra: object) -> dict[str, Any]:
    return {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": call_id, "content": content, **extra}
            ]
        },
    }


def _result(**fields: object) -> dict[str, Any]:
    return {"type": "result", "subtype": "success", "is_error": False, "result": "done", **fields}


@pytest.mark.parametrize("name", NAMES)
def test_feeding_a_fixtures_native_lines_yields_exactly_its_transcript_and_events(
    name: str,
) -> None:
    mapper = Mapper(FIXTURE_RUNNER_VERSION, LIMIT)
    got: list[Out] = []
    for line in recording(name):
        if "transcript" in line:
            got.extend(mapper.feed(line["transcript"].encode("utf-8")))
    assert got == _expected(name)


def test_system_init_maps_to_init_with_the_engines_version_model_and_tools() -> None:
    [init] = _feed(INIT)
    assert init == {
        "type": "init",
        "runner": {"name": "claude-code", "version": "1.0"},
        "effects": "translated",
        "engine": {"name": "claude-code", "version": "9.9.9", "model": "m"},
        "tools": ["Read"],
    }


def test_a_log_about_a_record_before_init_is_held_until_init_is_sent() -> None:
    events = _feed({"type": "system", "subtype": "ui_invalidate"}, INIT)
    assert [e["type"] for e in events] == ["init", "log"]
    assert events[1] == {
        "type": "log",
        "level": "debug",
        "message": "Claude Code record type system/ui_invalidate isn't mapped",
    }


def test_another_event_before_init_sends_a_synthetic_init_first() -> None:
    events = _feed(_assistant({"type": "text", "text": "hi"}))
    assert events[0] == {
        "type": "init",
        "runner": {"name": "claude-code", "version": "1.0"},
        "effects": "translated",
        "tools": [],
    }
    assert events[1] == {"type": "turn", "role": "assistant", "text": "hi"}


def test_an_init_record_after_a_synthetic_init_is_a_log_not_a_second_init() -> None:
    events = _feed(_assistant({"type": "text", "text": "hi"}), INIT)
    assert [e["type"] for e in events] == ["init", "turn", "log"]
    assert "9.9.9" in events[2]["message"]


def test_claude_code_ending_before_init_gets_a_synthetic_init_and_a_log_naming_the_exit_code() -> (
    None
):
    mapper = Mapper("1.0", LIMIT)
    events = [out.event for out in mapper.finish(1) if isinstance(out, Event)]
    assert [e["type"] for e in events] == ["init", "log"]
    assert events[1]["level"] == "error"
    assert "exit code 1" in events[1]["message"]


def test_claude_code_ending_after_init_adds_no_event() -> None:
    mapper = Mapper("1.0", LIMIT)
    _feed(INIT, mapper=mapper)
    assert mapper.finish(143) == []


def test_an_assistant_record_maps_to_a_turn_for_its_text_then_a_tool_call_per_tool_use() -> None:
    events = _feed(
        INIT,
        _assistant(
            {"type": "text", "text": "one"},
            {"type": "thinking", "thinking": "hidden"},
            {"type": "text", "text": "two"},
            _tool_use("toolu_1", file_path="/w/a", content="hi"),
            _tool_use("toolu_2", "Read", file_path="/w/a"),
        ),
    )[1:]
    assert events == [
        {"type": "turn", "role": "assistant", "text": "one\ntwo"},
        {
            "type": "tool_call",
            "callId": "toolu_1",
            "tool": "Write",
            "inputSummary": '{"file_path":"/w/a","content":"hi"}',
        },
        {
            "type": "tool_call",
            "callId": "toolu_2",
            "tool": "Read",
            "inputSummary": '{"file_path":"/w/a"}',
        },
    ]


def test_an_assistant_record_with_no_text_sends_no_turn() -> None:
    events = _feed(INIT, _assistant(_tool_use("toolu_1")))[1:]
    assert [e["type"] for e in events] == ["tool_call"]


def test_an_api_failure_maps_to_a_turn_with_its_text() -> None:
    events = _feed(
        INIT, _assistant({"type": "text", "text": "Invalid API key"}, error="authentication_failed")
    )
    assert events[1] == {"type": "turn", "role": "assistant", "text": "Invalid API key"}


def test_a_tool_result_maps_with_its_text_and_utf8_size() -> None:
    events = _feed(INIT, _assistant(_tool_use("toolu_1")), _tool_result("toolu_1", "1\thi"))
    assert events[2] == {
        "type": "tool_result",
        "callId": "toolu_1",
        "isError": False,
        "outputSummary": "1\thi",
        "outputBytes": 4,
    }


def test_a_tool_result_marked_is_error_maps_with_is_error_true() -> None:
    events = _feed(INIT, _assistant(_tool_use("t")), _tool_result("t", "no", is_error=True))
    assert events[2]["isError"] is True


def test_a_tool_results_text_blocks_are_joined_and_other_blocks_count_as_their_json() -> None:
    image = {"type": "image", "source": {"data": "AAAA"}}
    events = _feed(
        INIT,
        _assistant(_tool_use("t")),
        _tool_result("t", [{"type": "text", "text": "a"}, image, {"type": "text", "text": "é"}]),
    )
    assert events[2]["outputSummary"] == "a\né"
    assert events[2]["outputBytes"] == 1 + 2 + 1 + len(json.dumps(image, separators=(",", ":")))


def test_a_result_for_a_call_never_made_is_a_log_warning_naming_the_id() -> None:
    events = _feed(INIT, _tool_result("toolu_9", "x"))
    assert [e["type"] for e in events] == ["init", "log"]
    assert events[1]["level"] == "warning"
    assert "'toolu_9'" in events[1]["message"]


def _retry(error: str, status: int | None) -> dict[str, Any]:
    return {
        "type": "system",
        "subtype": "api_retry",
        "attempt": 1,
        "max_retries": 3,
        "retry_delay_ms": 500,
        "error_status": status,
        "error": error,
    }


@pytest.mark.parametrize(
    ("error", "status", "reason", "message"),
    [
        ("authentication_failed", 401, "authentication", "authentication_failed (HTTP 401)"),
        ("rate_limit", 429, "rate-limit", "rate_limit (HTTP 429)"),
        ("overloaded", 529, "server", "overloaded (HTTP 529)"),
        ("server_error", 500, "server", "server_error (HTTP 500)"),
        ("unknown", None, "network", "unknown (no HTTP response)"),
        ("invalid_request", 400, "other", "invalid_request (HTTP 400)"),
    ],
)
def test_an_api_retry_maps_to_retry_with_the_reason_its_error_and_status_name(
    error: str, status: int | None, reason: str, message: str
) -> None:
    assert _feed(INIT, _retry(error, status))[1] == {
        "type": "retry",
        "attempt": 1,
        "maxAttempts": 3,
        "delayMs": 500,
        "reason": reason,
        "message": message,
    }


def test_an_allowed_rate_limit_record_sends_no_event() -> None:
    record = {
        "type": "rate_limit_event",
        "rate_limit_info": {"status": "allowed", "rateLimitType": "five_hour"},
    }
    assert _feed(INIT, record)[1:] == []


def test_a_rejected_rate_limit_record_is_a_warning_naming_its_status_and_type() -> None:
    record = {
        "type": "rate_limit_event",
        "rate_limit_info": {"status": "rejected", "rateLimitType": "five_hour"},
    }
    assert _feed(INIT, record)[1] == {
        "type": "log",
        "level": "warning",
        "message": "rate limit rejected (five_hour)",
    }


def test_a_result_maps_its_status_message_turns_duration_usage_and_cost() -> None:
    usage = {
        "input_tokens": 6,
        "output_tokens": 253,
        "cache_read_input_tokens": 42158,
        "cache_creation_input_tokens": 5737,
        "service_tier": "standard",
    }
    record = _result(num_turns=3, duration_ms=3398, usage=usage, total_cost_usd=0.0017)
    assert _feed(INIT, record)[1] == {
        "type": "result",
        "status": "ok",
        "message": "done",
        "turns": 3,
        "durationMs": 3398,
        "usage": {
            "inputTokens": 6,
            "outputTokens": 253,
            "cacheReadTokens": 42158,
            "cacheWriteTokens": 5737,
        },
        "costUsd": 0.0017,
    }


def test_an_error_under_a_success_subtype_is_an_error_result() -> None:
    record = _result(is_error=True, result="Invalid API key")
    assert _feed(INIT, record)[1] == {
        "type": "result",
        "status": "error",
        "reason": "other",
        "message": "Invalid API key",
    }


def test_a_budget_stop_with_no_text_is_an_error_result_named_by_its_subtype() -> None:
    record = {"type": "result", "subtype": "error_max_budget_usd", "is_error": False}
    assert _feed(INIT, record)[1] == {
        "type": "result",
        "status": "error",
        "reason": "budget",
        "message": "error_max_budget_usd",
    }


# Requirement: An error result's reason comes from Claude Code's own fields


@pytest.mark.parametrize(
    ("subtype", "reason"),
    [
        ("error_max_turns", "turn-limit"),
        ("error_max_budget_usd", "budget"),
        ("error_during_execution", "engine"),
        ("error_widget", "other"),
    ],
)
def test_a_failed_subtype_maps_to_its_reason(subtype: str, reason: str) -> None:
    record = {"type": "result", "subtype": subtype, "is_error": True}
    (result,) = [e for e in _feed(INIT, record) if e["type"] == "result"]
    assert (result["status"], result["reason"]) == ("error", reason)


def test_an_ok_result_has_no_reason() -> None:
    (result,) = [e for e in _feed(INIT, _result()) if e["type"] == "result"]
    assert "reason" not in result


# Requirement: An API error maps by its error code, then the last retry, then its status


def _api_error(error: str) -> dict[str, Any]:
    """An assistant record standing for an API error, shaped like the recorded fixtures'."""
    return _assistant({"type": "text", "text": "API Error"}, error=error, is_api_error_message=True)


def _api_failure(status: int | None) -> dict[str, Any]:
    return _result(
        is_error=True, result="API Error", terminal_reason="api_error", api_error_status=status
    )


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("authentication_failed", "authentication"),
        ("billing_error", "quota"),
        ("rate_limit", "rate-limit"),
        ("max_output_tokens", "output-limit"),
    ],
)
def test_an_api_error_code_that_names_its_cause_gives_the_reason(error: str, reason: str) -> None:
    events = _feed(INIT, _retry("unknown", None), _api_error(error), _api_failure(None))
    assert events[-1]["reason"] == reason


def test_a_generic_api_error_after_retries_ends_with_the_last_retrys_reason() -> None:
    events = _feed(
        INIT,
        _retry("unknown", None),
        _retry("rate_limit", 429),
        _api_error("server_error"),
        _api_failure(429),
    )
    assert events[-1]["reason"] == "rate-limit"


@pytest.mark.parametrize(
    ("status", "reason"), [(503, "server"), (429, "rate-limit"), (None, "network"), (400, "other")]
)
def test_an_api_error_without_a_retry_or_a_named_code_goes_by_its_status(
    status: int | None, reason: str
) -> None:
    events = _feed(INIT, _api_error("widget_error"), _api_failure(status))
    assert events[-1]["reason"] == reason


def test_an_error_with_nothing_to_go_on_is_other() -> None:
    events = _feed(INIT, _result(is_error=True, result="?", terminal_reason="completed"))
    assert events[-1]["reason"] == "other"


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("is-error-success-subtype", "authentication"),
        ("rate-limit-retries", "rate-limit"),
        ("server-retries", "server"),
        ("network-retries", "network"),
    ],
)
def test_a_recorded_failure_maps_to_its_reason(name: str, reason: str) -> None:
    mapper = Mapper(FIXTURE_RUNNER_VERSION, LIMIT)
    events = [
        out.event
        for line in recording(name)
        if "transcript" in line
        for out in mapper.feed(line["transcript"].encode())
        if isinstance(out, Event)
    ]
    assert (events[-1]["type"], events[-1]["reason"]) == ("result", reason)


def test_permission_denials_are_warnings_immediately_before_the_result() -> None:
    denials = [{"tool_name": "Write"}, {"tool_name": "Write"}, {"tool_name": "Bash"}]
    events = _feed(INIT, _result(permission_denials=denials))[1:]
    assert events[:2] == [
        {"type": "log", "level": "warning", "message": "permissions denied Write (2 times)"},
        {"type": "log", "level": "warning", "message": "permissions denied Bash"},
    ]
    assert events[2]["type"] == "result"


# Requirement: An assistant message's other model is a served_model event
# Built on the recorded shapes: every recording's assistant records name init's model, or
# <synthetic> for the API errors Claude Code reports itself.

INIT_OPUS = {**INIT, "model": "claude-opus-5-5"}


def _said_by(model: object, *content: dict[str, Any], **extra: object) -> dict[str, Any]:
    return {"type": "assistant", "message": {"model": model, "content": list(content)}, **extra}


def test_a_fallback_models_message_sends_served_model_before_its_turn_and_calls() -> None:
    said = _said_by("claude-sonnet-5-5", {"type": "text", "text": "hi"}, _tool_use("toolu_1"))
    assert [e["type"] for e in _feed(INIT_OPUS, said)] == [
        "init",
        "served_model",
        "turn",
        "tool_call",
    ]
    assert _feed(INIT_OPUS, said)[1] == {"type": "served_model", "model": "claude-sonnet-5-5"}


def test_a_message_claude_code_made_itself_sends_no_served_model() -> None:
    said = _said_by("<synthetic>", {"type": "text", "text": "API Error: 401"})
    assert [e["type"] for e in _feed(INIT_OPUS, said)] == ["init", "turn"]


def test_messages_from_inits_own_model_send_no_served_model() -> None:
    said = _said_by("claude-opus-5-5", {"type": "text", "text": "hi"})
    assert [e["type"] for e in _feed(INIT_OPUS, said, said)] == ["init", "turn", "turn"]


def test_a_subagents_message_from_another_model_counts_the_same_and_only_once() -> None:
    said = _said_by(
        "claude-haiku-5-5", {"type": "text", "text": "found it"}, parent_tool_use_id="toolu_9"
    )
    events = _feed(INIT_OPUS, said, said)
    assert [e for e in events if e["type"] == "served_model"] == [
        {"type": "served_model", "model": "claude-haiku-5-5"}
    ]


def test_a_model_that_isnt_a_string_sends_no_served_model() -> None:
    said = _said_by(7, {"type": "text", "text": "hi"})
    assert [e["type"] for e in _feed(INIT_OPUS, said)] == ["init", "turn"]


# Requirement: The result's other models are served_model events before it


def test_a_model_only_the_results_model_usage_names_is_sent_before_denials_and_the_result() -> None:
    used: dict[str, dict[str, int]] = {
        "claude-opus-5-5": {},
        "claude-haiku-5-5": {},
        "<synthetic>": {},
    }
    record = _result(modelUsage=used, permission_denials=[{"tool_name": "Bash"}])
    events = _feed(INIT_OPUS, record)[1:]
    assert [e["type"] for e in events] == ["served_model", "log", "result"]
    assert events[0] == {"type": "served_model", "model": "claude-haiku-5-5"}


def test_a_model_usage_model_already_reported_is_not_sent_again() -> None:
    said = _said_by("claude-sonnet-5-5", {"type": "text", "text": "hi"})
    record = _result(modelUsage={"claude-sonnet-5-5": {}, "claude-opus-5-5": {}})
    events = _feed(INIT_OPUS, said, record)
    assert [e["model"] for e in events if e["type"] == "served_model"] == ["claude-sonnet-5-5"]


def test_with_no_init_record_every_model_is_served_once() -> None:
    # No system/init, so the synthetic init names no model and each model that answered is new.
    said = _said_by("claude-opus-5-5", {"type": "text", "text": "hi"})
    events = _feed(said, _result(modelUsage={"claude-opus-5-5": {}}))
    assert [e["type"] for e in events] == ["init", "served_model", "turn", "result"]


def test_a_result_record_it_cant_read_is_a_log_error_and_no_result() -> None:
    mapper = Mapper("1.0", LIMIT)
    events = _feed(INIT, {"type": "result", "subtype": "success"}, mapper=mapper)
    assert [e["type"] for e in events] == ["init", "log"]
    assert events[1]["level"] == "error"
    assert not mapper.result_sent


def test_nothing_after_the_result_maps_to_an_event_but_every_line_is_kept() -> None:
    mapper = Mapper("1.0", LIMIT)
    _feed(INIT, _result(), mapper=mapper)
    out = mapper.feed(json.dumps(_assistant({"type": "text", "text": "late"})).encode())
    assert [type(o) for o in out] == [Transcript]


def test_an_unknown_record_type_is_noted_once_at_debug_and_both_lines_are_kept() -> None:
    mapper = Mapper("1.0", LIMIT)
    outs = [*mapper.feed(json.dumps(INIT).encode())]
    for _ in range(2):
        outs.extend(mapper.feed(b'{"type":"widget"}'))
    events = [o.event for o in outs if isinstance(o, Event)]
    assert events[1:] == [
        {"type": "log", "level": "debug", "message": "Claude Code record type widget isn't mapped"}
    ]
    assert [o.record for o in outs if isinstance(o, Transcript)][1:] == ['{"type":"widget"}'] * 2


@pytest.mark.parametrize(
    "line",
    [b"Update available", b"[1, 2]", b'{"type": "a", "type": "b"}', b'{"x": NaN}'],
)
def test_a_line_that_isnt_a_json_object_is_a_warning_and_is_kept_verbatim(line: bytes) -> None:
    mapper = Mapper("1.0", LIMIT)
    _feed(INIT, mapper=mapper)
    out = mapper.feed(line)
    assert out[0] == Transcript(line.decode())
    assert out[1] == Event(
        {
            "type": "log",
            "level": "warning",
            "message": "Claude Code wrote a line that isn't a JSON object",
        }
    )


def test_a_line_that_isnt_utf8_is_kept_as_base64() -> None:
    mapper = Mapper("1.0", LIMIT)
    assert mapper.feed(b"\xff\xfe")[0] == Transcript("//4=", "base64")


def test_a_known_record_missing_a_field_its_mapping_needs_is_a_log_error() -> None:
    events = _feed(INIT, {"type": "assistant", "message": {}})
    assert events[1]["level"] == "error"
    assert "message.content" in events[1]["message"]


def test_after_silence_lines_are_kept_but_map_to_no_event() -> None:
    mapper = Mapper("1.0", LIMIT)
    _feed(INIT, mapper=mapper)
    mapper.silence()
    assert mapper.feed(json.dumps(_result()).encode()) == [Transcript(json.dumps(_result()))]
    assert mapper.finish(143) == []


def test_a_one_mebibyte_tool_output_is_cut_to_fit_and_keeps_its_true_size() -> None:
    output = "é" * (512 * 1024)
    events = _feed(INIT, _assistant(_tool_use("t")), _tool_result("t", output))
    result = events[2]
    assert event_size(result) <= LIMIT
    assert result["outputBytes"] == 1024 * 1024
    assert result["outputSummary"].endswith(" bytes left out]")


def test_a_summary_is_cut_further_when_the_event_limit_is_below_the_summary_limit() -> None:
    mapper = Mapper("1.0", event_max_bytes=600, summary_max_bytes=4096)
    events = _feed(INIT, _assistant({"type": "text", "text": "x" * 5000}), mapper=mapper)
    assert event_size(events[1]) <= 600


@pytest.mark.parametrize("limit", [10, 30, 31, 32, 33, 100])
def test_cut_ends_on_a_utf8_boundary_within_the_limit_naming_the_bytes_left_out(limit: int) -> None:
    text = "日本語のテキスト" * 20
    cut_text = cut(text, limit)
    size = len(cut_text.encode("utf-8"))
    head, _, suffix = cut_text.partition(" … [")
    assert size <= limit or head == ""
    assert text.startswith(head)
    assert suffix == f"{len(text.encode()) - len(head.encode())} bytes left out]"


def test_cut_leaves_a_text_that_fits_unchanged() -> None:
    assert cut("short", 100) == "short"


def test_an_api_error_that_recovered_doesnt_name_a_later_failure() -> None:
    events = _feed(
        INIT,
        _retry("rate_limit", 429),
        _api_error("rate_limit"),
        _assistant({"type": "text", "text": "carrying on"}),
        _result(is_error=True, result="?", terminal_reason="completed"),
    )
    assert events[-1]["reason"] == "other"
