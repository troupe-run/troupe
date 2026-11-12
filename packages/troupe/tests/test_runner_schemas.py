"""Tests for the runner contract's schemas (spec: runner-protocol)."""

from collections.abc import Iterator
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from protocol_schemas import validator_for
from runner_schemas import RUNNER_SCHEMAS, is_valid, load, validate

RUN_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
HASH = "sha256:" + "ab" * 32


def _refs(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


# Requirement: The contract is JSON Schema in the protocol directory


# The draft, $id and reference checks for every schema are in test_protocol_strict.py.


def _request(method: str, params: dict[str, Any], id_: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}


def _notification(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}


START: dict[str, Any] = {
    "runId": RUN_ID,
    "direction": "write hello.txt",
    "workspace": "/workspace",
    "effects": {"write": [], "delete": [], "move": []},
    "scratch": "/scratch",
    "onContextFull": "fail",
    "options": {"script": {"steps": [{"wait": {"ms": 1}}]}},
    "limits": {"eventMaxBytes": 65536},
}

ERROR_DATA = {
    "code": "runner.unsupported-version",
    "problem": "p",
    "fix": "f",
    "details": {"supportedVersions": [0]},
}

# (schema, a valid example, an invalid example)
EXAMPLES: list[tuple[str, object, object]] = [
    (
        "initialize.schema.json",
        _request(
            "initialize",
            {
                "protocolVersions": [0],
                "host": {"name": "troupe", "version": "1"},
                "capabilities": [],
            },
        ),
        _request(
            "initialize",
            {
                "protocolVersions": [],
                "host": {"name": "troupe", "version": "1"},
                "capabilities": [],
            },
        ),
    ),
    (
        "initialize.schema.json#/$defs/result",
        {
            "protocolVersion": 0,
            "runner": {"name": "scripted", "version": "0.1"},
            "capabilities": ["transcript-kinds"],
        },
        {
            "protocolVersion": 0,
            "runner": {"name": "scripted", "version": "0.1"},
            "capabilities": ["transcript-kinds", "transcript-kinds"],
        },
    ),
    (
        "run-start.schema.json",
        _request("run/start", START),
        _request("run/start", {**START, "runId": "has spaces"}),
    ),
    ("run-start.schema.json#/$defs/result", {"runId": RUN_ID}, {}),
    (
        "run-cancel.schema.json",
        _request("run/cancel", {"runId": RUN_ID}),
        _request("run/cancel", {}),
    ),
    ("run-cancel.schema.json#/$defs/result", {}, {"extra": True}),
    ("shutdown.schema.json", _request("shutdown", {}), _request("shutdown", {"now": True})),
    ("shutdown.schema.json#/$defs/result", {}, {"extra": True}),
    (
        "run-transcript.schema.json",
        _notification("run/transcript", {"runId": RUN_ID, "record": '{"type":"x"}'}),
        _notification("run/transcript", {"runId": RUN_ID, "record": "x", "encoding": "latin-1"}),
    ),
    (
        "run-event.schema.json",
        _notification(
            "run/event",
            {
                "runId": RUN_ID,
                "seq": 0,
                "type": "init",
                "runner": {"name": "s", "version": "1"},
                "effects": "checked",
                "tools": [],
            },
        ),
        _notification(
            "run/event",
            {
                "runId": RUN_ID,
                "seq": 1,
                "type": "init",
                "runner": {"name": "s", "version": "1"},
                "effects": "checked",
                "tools": [],
            },
        ),
    ),
    (
        "error-response.schema.json",
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "m", "data": ERROR_DATA}},
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "m"}},
    ),
    (
        "jsonrpc.schema.json#/$defs/successResponse",
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        {"jsonrpc": "1.0", "id": 1, "result": {}},
    ),
]


@pytest.mark.parametrize(("ref", "valid", "invalid"), EXAMPLES, ids=[e[0] for e in EXAMPLES])
def test_each_message_schema_accepts_a_valid_example_and_refuses_an_invalid_one(
    ref: str, valid: object, invalid: object
) -> None:
    validate(valid, ref)
    assert not is_valid(invalid, ref)


# Requirement: A transcript record can say what kind it is


@pytest.mark.parametrize("kind", ["sent", "received", "note"])
def test_a_transcript_record_with_each_kind_validates(kind: str) -> None:
    validate(
        _notification("run/transcript", {"runId": RUN_ID, "record": "x", "kind": kind}),
        "run-transcript.schema.json",
    )


def test_a_transcript_record_without_a_kind_validates() -> None:
    validate(
        _notification("run/transcript", {"runId": RUN_ID, "record": "x"}),
        "run-transcript.schema.json",
    )


def test_a_transcript_record_of_an_unknown_kind_does_not_validate() -> None:
    record = {"runId": RUN_ID, "record": "x", "kind": "request"}
    assert not is_valid(_notification("run/transcript", record), "run-transcript.schema.json")


# Requirement: The transcript-kinds capability


def test_an_initialize_answer_naming_transcript_kinds_validates() -> None:
    result = {"protocolVersion": 0, "runner": {"name": "s", "version": "1"}}
    validate(
        {**result, "capabilities": ["transcript-kinds"]}, "initialize.schema.json#/$defs/result"
    )


def test_a_capability_the_contract_doesnt_define_does_not_validate_offered_or_answered() -> None:
    result = {
        "protocolVersion": 0,
        "runner": {"name": "s", "version": "1"},
        "capabilities": ["widgets"],
    }
    offer = {
        "protocolVersions": [0],
        "host": {"name": "troupe", "version": "1"},
        "capabilities": ["widgets"],
    }
    assert not is_valid(result, "initialize.schema.json#/$defs/result")
    assert not is_valid(_request("initialize", offer), "initialize.schema.json")


EVENTS: dict[str, dict[str, Any]] = {
    "init": {
        "runner": {"name": "s", "version": "1"},
        "effects": "translated",
        "tools": ["Write"],
        "engine": {"name": "claude-code", "version": "2.1.281", "model": "m"},
    },
    "turn": {"role": "assistant", "text": "hello"},
    "tool_call": {"callId": "c1", "tool": "Write", "inputSummary": "out/hello.txt"},
    "tool_result": {"callId": "c1", "isError": False, "outputSummary": "ok", "outputBytes": 2},
    "retry": {"attempt": 1, "maxAttempts": 10, "delayMs": 500, "reason": "authentication"},
    "context": {
        "kind": "compacted",
        "by": "engine",
        "message": "the engine summarised the earlier conversation",
        "tokensBefore": 41000,
        "tokensAfter": 9000,
        "messagesBefore": 120,
        "messagesAfter": 34,
    },
    "log": {"level": "info", "message": "starting"},
    "served_model": {"model": "gpt-6-luna-2026-03-05"},
    "result": {
        "status": "error",
        "reason": "authentication",
        "message": "401",
        "turns": 1,
        "durationMs": 10,
        "usage": {"inputTokens": 3, "outputTokens": 5, "cacheReadTokens": 0, "cacheWriteTokens": 1},
        "costUsd": 0.0,
    },
}


@pytest.mark.parametrize("type_", sorted(EVENTS))
def test_each_run_event_type_is_accepted_with_its_fields(type_: str) -> None:
    seq = 0 if type_ == "init" else 3
    event = {"runId": RUN_ID, "seq": seq, "type": type_, **EVENTS[type_]}
    validate(event, "run-event.schema.json#/$defs/event")
    validate(_notification("run/event", event), "message.schema.json#/$defs/fromRunner")


def test_an_event_of_an_unknown_type_is_refused() -> None:
    event = {"runId": RUN_ID, "seq": 2, "type": "thought", "text": "hmm"}
    assert not is_valid(event, "run-event.schema.json#/$defs/event")


def test_the_oversized_event_is_a_host_event_but_never_a_runner_event() -> None:
    event = {
        "runId": RUN_ID,
        "seq": 4,
        "type": "oversized",
        "originalType": "tool_result",
        "bytes": 70000,
        "ref": HASH,
    }
    validate(event, "run-event.schema.json#/$defs/hostEvent")
    assert not is_valid(event, "run-event.schema.json#/$defs/event")


# Requirement: A context event names what happened from a closed list (and says who, and how much)


def _context(**fields: object) -> dict[str, Any]:
    event: dict[str, Any] = {
        "runId": RUN_ID,
        "seq": 2,
        "type": "context",
        "kind": "compacted",
        "by": "engine",
        "message": "compacted",
    }
    event.update(fields)
    return {name: value for name, value in event.items() if value is not ...}


@pytest.mark.parametrize(
    ("kind", "by"), [("compacted", "engine"), ("truncated", "runner"), ("other", "runner")]
)
def test_a_context_event_of_each_listed_kind_and_by_validates(kind: str, by: str) -> None:
    validate(_context(kind=kind, by=by), "run-event.schema.json#/$defs/event")


def test_a_context_event_whose_kind_is_the_runners_own_does_not_validate() -> None:
    assert not is_valid(_context(kind="pruned"), "run-event.schema.json#/$defs/event")


def test_a_context_event_whose_by_is_off_the_list_does_not_validate() -> None:
    assert not is_valid(_context(by="host"), "run-event.schema.json#/$defs/event")


@pytest.mark.parametrize("field", ["kind", "by", "message"])
def test_a_context_event_without_a_required_field_does_not_validate(field: str) -> None:
    assert not is_valid(_context(**{field: ...}), "run-event.schema.json#/$defs/event")


def test_a_context_event_with_only_tokens_before_validates() -> None:
    validate(_context(tokensBefore=41000), "run-event.schema.json#/$defs/event")


def test_a_context_event_with_only_the_message_counts_validates() -> None:
    validate(
        _context(kind="truncated", by="runner", messagesBefore=120, messagesAfter=34),
        "run-event.schema.json#/$defs/event",
    )


@pytest.mark.parametrize(
    "field", ["tokensBefore", "tokensAfter", "messagesBefore", "messagesAfter"]
)
def test_a_context_event_with_a_null_or_negative_count_does_not_validate(field: str) -> None:
    assert not is_valid(_context(**{field: None}), "run-event.schema.json#/$defs/event")
    assert not is_valid(_context(**{field: -1}), "run-event.schema.json#/$defs/event")


def test_a_context_event_with_a_count_the_contract_doesnt_define_does_not_validate() -> None:
    assert not is_valid(_context(turnsBefore=3), "run-event.schema.json#/$defs/event")


def test_an_oversized_context_event_is_a_host_event() -> None:
    event = {
        "runId": RUN_ID,
        "seq": 2,
        "type": "oversized",
        "originalType": "context",
        "bytes": 70000,
        "ref": HASH,
    }
    validate(event, "run-event.schema.json#/$defs/hostEvent")


# Requirement: The contract is not specific to one engine


def _event_defs() -> dict[str, dict[str, Any]]:
    defs: dict[str, dict[str, Any]] = load(RUNNER_SCHEMAS / "run-event.schema.json")["$defs"]
    return {name: defs[name] for name in EVENTS}


def test_no_event_type_requires_engine_specific_fields() -> None:
    for name, schema in _event_defs().items():
        assert "engine" not in schema["required"], name


@pytest.mark.parametrize("type_", sorted(EVENTS))
def test_no_run_event_type_accepts_native_engine_detail(type_: str) -> None:
    seq = 0 if type_ == "init" else 3
    event = {"runId": RUN_ID, "seq": seq, "type": type_, **EVENTS[type_], "native": {"k": 1}}
    assert not is_valid(event, "run-event.schema.json#/$defs/event")


# Requirement: An error result names one reason from a closed list
# Requirement: A recorded result keeps the same rule

FAILURE_REASONS = [
    "authentication",
    "quota",
    "rate-limit",
    "network",
    "server",
    "configuration",
    "context-length",
    "output-limit",
    "refused",
    "turn-limit",
    "budget",
    "cancelled",
    "engine",
    "runner",
    "other",
]

RESULT_WHEREVER_IT_APPEARS = [
    "run-event.schema.json#/$defs/event",
    "run-event.schema.json#/$defs/hostEvent",
    "../events/run-ended.schema.json#/properties/outcome/properties/result",
]


def _bare_result(**fields: object) -> dict[str, Any]:
    return {"runId": RUN_ID, "seq": 3, "type": "result", "message": "m", **fields}


def test_the_failure_reasons_are_the_fifteen_the_contract_names() -> None:
    defs = load(RUNNER_SCHEMAS / "run-event.schema.json")["$defs"]
    assert defs["failureReason"]["enum"] == FAILURE_REASONS


@pytest.mark.parametrize("ref", RESULT_WHEREVER_IT_APPEARS)
@pytest.mark.parametrize("reason", FAILURE_REASONS)
def test_an_error_result_with_each_reason_validates_wherever_a_result_appears(
    ref: str, reason: str
) -> None:
    validate(_bare_result(status="error", reason=reason), ref)


@pytest.mark.parametrize("ref", RESULT_WHEREVER_IT_APPEARS)
def test_an_ok_result_without_a_reason_validates_wherever_a_result_appears(ref: str) -> None:
    validate(_bare_result(status="ok"), ref)


@pytest.mark.parametrize("ref", RESULT_WHEREVER_IT_APPEARS)
@pytest.mark.parametrize(
    "result",
    [
        _bare_result(status="error"),
        _bare_result(status="error", reason="timeout"),
        _bare_result(status="ok", reason="budget"),
    ],
    ids=["error without a reason", "a reason off the list", "ok with a reason"],
)
def test_a_result_breaking_the_reason_rule_is_refused_wherever_it_appears(
    ref: str, result: dict[str, Any]
) -> None:
    assert not is_valid(result, ref)


def test_an_error_result_without_a_reason_is_refused_as_a_runner_message() -> None:
    message = _notification("run/event", _bare_result(status="error"))
    assert not is_valid(message, "message.schema.json#/$defs/fromRunner")


RETRY_REASONS = ["authentication", "rate-limit", "network", "server", "other"]


@pytest.mark.parametrize("reason", RETRY_REASONS)
def test_a_retry_with_each_of_its_reasons_validates(reason: str) -> None:
    retry = {"runId": RUN_ID, "seq": 2, "type": "retry", "attempt": 1, "delayMs": 0}
    validate({**retry, "reason": reason}, "run-event.schema.json#/$defs/event")


# Requirement: A result says when a retry wasn't safe
# Requirement: Only a failure a retry can name carries notRetried


def test_the_retry_reasons_are_one_named_list_both_events_use() -> None:
    defs = load(RUNNER_SCHEMAS / "run-event.schema.json")["$defs"]
    assert defs["retryReason"]["enum"] == RETRY_REASONS
    assert defs["retry"]["properties"]["reason"] == {"$ref": "#/$defs/retryReason"}


def test_the_not_retried_values_are_the_one_the_contract_names() -> None:
    defs = load(RUNNER_SCHEMAS / "run-event.schema.json")["$defs"]
    assert defs["notRetried"]["enum"] == ["side-effect"]


@pytest.mark.parametrize("ref", RESULT_WHEREVER_IT_APPEARS)
@pytest.mark.parametrize("reason", RETRY_REASONS)
def test_an_error_result_not_retried_for_a_side_effect_validates_wherever_a_result_appears(
    ref: str, reason: str
) -> None:
    validate(_bare_result(status="error", reason=reason, notRetried="side-effect"), ref)


@pytest.mark.parametrize("ref", RESULT_WHEREVER_IT_APPEARS)
@pytest.mark.parametrize(
    "result",
    [
        _bare_result(status="ok", notRetried="side-effect"),
        *(
            _bare_result(status="error", reason=reason, notRetried="side-effect")
            for reason in FAILURE_REASONS
            if reason not in RETRY_REASONS
        ),
        _bare_result(status="error", reason="network", notRetried="unsafe"),
        _bare_result(status="error", reason="network", notRetried=None),
    ],
    ids=[
        "ok",
        *(f"reason {r}" for r in FAILURE_REASONS if r not in RETRY_REASONS),
        "a value off the list",
        "null",
    ],
)
def test_a_result_breaking_the_not_retried_rule_is_refused_wherever_it_appears(
    ref: str, result: dict[str, Any]
) -> None:
    assert not is_valid(result, ref)


def test_a_result_not_retried_beside_a_reason_no_retry_names_is_refused_as_a_runner_message() -> (
    None
):
    result = _bare_result(status="error", reason="budget", notRetried="side-effect")
    assert not is_valid(_notification("run/event", result), "message.schema.json#/$defs/fromRunner")


def test_no_runner_can_extend_the_not_retried_values() -> None:
    defs = load(RUNNER_SCHEMAS / "run-event.schema.json")["$defs"]
    assert list(_dynamic_refs(defs["notRetried"])) == []


def _dynamic_refs(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$dynamicRef" and isinstance(value, str):
                yield value
            else:
                yield from _dynamic_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _dynamic_refs(item)


def test_no_runner_can_extend_the_failure_reasons() -> None:
    defs = load(RUNNER_SCHEMAS / "run-event.schema.json")["$defs"]
    assert list(_dynamic_refs(defs["failureReason"])) == []
    assert list(_dynamic_refs(defs["result"])) == []


# Requirement: A served model's name has a model's shape


@pytest.mark.parametrize("model", ["", "m" * 257, "bad\nname", "tab\there", "del\x7f"])
def test_a_served_model_outside_a_models_shape_does_not_validate(model: str) -> None:
    event = {"runId": RUN_ID, "seq": 3, "type": "served_model", "model": model}
    assert not is_valid(event, "run-event.schema.json#/$defs/event")


def test_a_served_model_of_256_characters_validates() -> None:
    event = {"runId": RUN_ID, "seq": 3, "type": "served_model", "model": "m" * 256}
    validate(event, "run-event.schema.json#/$defs/event")


def test_a_served_model_without_its_model_does_not_validate() -> None:
    event = {"runId": RUN_ID, "seq": 3, "type": "served_model"}
    assert not is_valid(event, "run-event.schema.json#/$defs/event")


def test_an_oversized_served_model_is_a_host_event() -> None:
    event = {
        "runId": RUN_ID,
        "seq": 4,
        "type": "oversized",
        "originalType": "served_model",
        "bytes": 70000,
        "ref": HASH,
    }
    validate(event, "run-event.schema.json#/$defs/hostEvent")


def test_a_usage_counter_the_contract_doesnt_name_is_refused() -> None:
    event = {"runId": RUN_ID, "seq": 3, "type": "result", **EVENTS["result"]}
    event["usage"] = {"reasoningTokens": 2}
    assert not is_valid(event, "run-event.schema.json#/$defs/event")


# Requirement: Usage's input counters add up to the whole input
# Requirement: A cache counter left out was not reported


def test_usage_says_input_counters_add_up_and_an_absent_cache_counter_wasnt_reported() -> None:
    usage = _event_defs()["result"]["properties"]["usage"]
    counters = usage["properties"]
    assert "add up to the run's whole input" in usage["description"]
    assert "cacheReadTokens" in counters["inputTokens"]["description"]
    assert "cacheWriteTokens" in counters["inputTokens"]["description"]
    assert "stays in inputTokens" in counters["inputTokens"]["description"]
    for name in ("cacheReadTokens", "cacheWriteTokens"):
        assert "Absent: the runner couldn't report them" in counters[name]["description"], name


_CONTROL = [chr(c) for c in [*range(0x20), 0x7F]]


def _strategy(schema: dict[str, Any]) -> st.SearchStrategy[Any]:
    """Values for the small subset of JSON Schema the required event fields use."""
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref.endswith("/runId"):
            return st.uuids().map(str)
        if ref.endswith("/named"):
            return st.fixed_dictionaries(
                {"name": st.text(min_size=1), "version": st.text(min_size=1)}
            )
        if ref.endswith("/seq"):
            return st.integers(min_value=1)
        if ref.endswith("/retryReason"):
            return st.sampled_from(RETRY_REASONS)
        if ref.endswith("/model"):
            return st.text(
                st.characters(blacklist_categories=["Cs"], blacklist_characters=_CONTROL),
                min_size=1,
                max_size=256,
            )
        raise AssertionError(f"no strategy for {ref}")
    if "const" in schema:
        return st.just(schema["const"])
    if "enum" in schema:
        return st.sampled_from(schema["enum"])
    kind = schema["type"]
    if kind == "string":
        return st.text(min_size=schema.get("minLength", 0))
    if kind == "integer":
        return st.integers(min_value=schema.get("minimum", 0))
    if kind == "boolean":
        return st.booleans()
    if kind == "array":
        return st.lists(_strategy(schema["items"]), max_size=3)
    raise AssertionError(f"no strategy for {schema}")


def _minimal_events() -> st.SearchStrategy[dict[str, Any]]:
    """Events with only their required fields, filled with generic, engine-free values."""
    choices = [
        st.fixed_dictionaries(
            {
                field: _strategy(schema["properties"][field])
                for field in _sent_required(name, schema)
            }
        ).flatmap(_with_reason_when_failed)
        for name, schema in _event_defs().items()
    ]
    return st.one_of(choices)


def _with_reason_when_failed(event: dict[str, Any]) -> st.SearchStrategy[dict[str, Any]]:
    """An error result's reason is required by its status, not by the def's required list."""
    if event.get("type") != "result" or event["status"] != "error":
        return st.just(event)
    return st.sampled_from(FAILURE_REASONS).map(lambda reason: {**event, "reason": reason})


def _sent_required(name: str, schema: dict[str, Any]) -> list[str]:
    """What a runner must send: the def's required fields, and init's effects, which only a
    recorded init may lack (declared-effects)."""
    return [*schema["required"], "effects"] if name == "init" else list(schema["required"])


@settings(max_examples=200, deadline=None)
@given(event=_minimal_events())
def test_every_event_type_is_valid_with_only_generic_required_fields(event: dict[str, Any]) -> None:
    validate(event, "run-event.schema.json#/$defs/event")


def test_an_init_event_from_a_runner_without_a_model_or_engine_is_valid() -> None:
    event = {
        "runId": RUN_ID,
        "seq": 0,
        "type": "init",
        "runner": {"name": "scripted", "version": "0.1.0"},
        "effects": "checked",
        "tools": [],
    }
    validate(event, "run-event.schema.json#/$defs/event")


# Requirement: Run start carries everything the runner may use


@pytest.mark.parametrize(
    "run_id", ["run-1", "", "0F8FAD5B-D9CB-469F-A165-70867728950E", "0f8fad5b"]
)
def test_a_run_start_whose_run_id_is_not_a_canonical_lowercase_uuid_does_not_validate(
    run_id: str,
) -> None:
    assert not is_valid(_request("run/start", {**START, "runId": run_id}), "run-start.schema.json")
    validate(_request("run/start", START), "run-start.schema.json")


# Requirement: Run start carries the run's runtime

RUNTIME = {
    "name": "openai",
    "endpoint": "https://api.openai.com/v1",
    "model": "gpt-test",
    "credential": True,
}


def test_a_run_start_with_a_runtime_validates() -> None:
    validate(_request("run/start", {**START, "runtime": RUNTIME}), "run-start.schema.json")
    validate(
        _request("run/start", {**START, "runtime": {**RUNTIME, "credential": False}}),
        "run-start.schema.json",
    )


@pytest.mark.parametrize(
    "runtime",
    [
        pytest.param({**RUNTIME, "value": "sk-test"}, id="a credential's value"),
        pytest.param({**RUNTIME, "env": "OPENAI_API_KEY"}, id="the variable's name"),
        pytest.param({**RUNTIME, "credential": {"env": "OPENAI_API_KEY"}}, id="a reference"),
        pytest.param({k: v for k, v in RUNTIME.items() if k != "model"}, id="no model"),
        pytest.param({**RUNTIME, "endpoint": "https://u:p@example.com"}, id="user info"),
        pytest.param(None, id="a null for no runtime"),
    ],
)
def test_a_run_start_whose_runtime_holds_anything_else_does_not_validate(
    runtime: object,
) -> None:
    assert not is_valid(
        _request("run/start", {**START, "runtime": runtime}), "run-start.schema.json"
    )


# Requirement: Run start carries the run's runtime (a price for the run's model)
# Requirement: A price is in US dollars per million tokens

PRICE = {"input": 2, "output": 8, "cacheRead": 0.5, "cacheWrite": 2.5}


@pytest.mark.parametrize(
    "price",
    [
        pytest.param({"input": 2, "output": 8}, id="input and output only"),
        pytest.param(PRICE, id="every rate"),
        pytest.param({"input": 0, "output": 0.0}, id="free"),
    ],
)
def test_a_run_start_whose_runtime_carries_a_price_validates(price: dict[str, Any]) -> None:
    validate(
        _request("run/start", {**START, "runtime": {**RUNTIME, "price": price}}),
        "run-start.schema.json",
    )


@pytest.mark.parametrize(
    "price",
    [
        pytest.param({"input": 2}, id="no output rate"),
        pytest.param({"output": 8}, id="no input rate"),
        pytest.param({**PRICE, "cacheRead": -1}, id="a negative rate"),
        pytest.param({**PRICE, "currency": "EUR"}, id="an unknown field"),
        pytest.param({**PRICE, "input": "2"}, id="a rate as text"),
        pytest.param({**PRICE, "output": True}, id="a rate as a boolean"),
        pytest.param(None, id="a null for no price"),
    ],
)
def test_a_run_start_whose_price_isnt_one_does_not_validate(price: object) -> None:
    assert not is_valid(
        _request("run/start", {**START, "runtime": {**RUNTIME, "price": price}}),
        "run-start.schema.json",
    )


# Requirement: The result event states what the runner saw (a reported cost and an estimate)


def _result(**costs: object) -> dict[str, Any]:
    event = {"runId": RUN_ID, "seq": 3, "type": "result", **EVENTS["result"]}
    del event["costUsd"]
    return {**event, **costs}


@pytest.mark.parametrize(
    "costs",
    [
        pytest.param({"costUsd": 0.42}, id="a reported cost"),
        pytest.param({"estimatedCostUsd": 0.42}, id="an estimate"),
        pytest.param({}, id="neither"),
    ],
)
def test_a_result_with_at_most_one_of_the_costs_validates(costs: dict[str, Any]) -> None:
    validate(_result(**costs), "run-event.schema.json#/$defs/event")


def test_a_result_with_a_reported_cost_and_an_estimate_together_does_not_validate() -> None:
    assert not is_valid(
        _result(costUsd=0.42, estimatedCostUsd=0.4), "run-event.schema.json#/$defs/event"
    )


def test_a_negative_estimate_does_not_validate() -> None:
    assert not is_valid(_result(estimatedCostUsd=-0.1), "run-event.schema.json#/$defs/event")


# Requirement: A success result matches its method's result schema

SUCCESS = "jsonrpc.schema.json#/$defs/successResponse"


@pytest.mark.parametrize(
    "result",
    [
        {"protocolVersion": 0, "runner": {"name": "s", "version": "1"}, "capabilities": []},
        {"runId": RUN_ID},
        {},
    ],
    ids=["initialize", "run/start", "run/cancel and shutdown"],
)
def test_a_success_response_carrying_a_methods_real_result_is_accepted(
    result: dict[str, Any],
) -> None:
    validate({"jsonrpc": "2.0", "id": 1, "result": result}, SUCCESS)


@pytest.mark.parametrize(
    "result",
    [{"x": 1}, {"runId": RUN_ID, "extra": True}],
    ids=["no method's result", "run/start result with an extra key"],
)
def test_a_success_response_whose_result_no_method_defines_is_refused(
    result: dict[str, Any],
) -> None:
    assert not is_valid({"jsonrpc": "2.0", "id": 1, "result": result}, SUCCESS)


# Requirement: Failures use the shared error shape

ERROR_RESPONSE = "error-response.schema.json"


def _error_response(data: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "m", "data": data}}


@pytest.mark.parametrize(
    "code",
    [
        "runner.parse-error",
        "runner.invalid-request",
        "runner.not-initialized",
        "runner.unknown-method",
        "runner.already-started",
        "runner.invalid-params",
    ],
)
def test_each_contract_error_code_without_details_validates_and_refuses_details(code: str) -> None:
    data = {"code": code, "problem": "p", "fix": "f"}
    validate(_error_response(data), ERROR_RESPONSE)
    assert not is_valid(_error_response({**data, "details": {"x": 1}}), ERROR_RESPONSE)


def test_unsupported_version_must_name_the_versions_the_runner_supports() -> None:
    data = {"code": "runner.unsupported-version", "problem": "p", "fix": "f"}
    assert not is_valid(_error_response(data), ERROR_RESPONSE)
    validate(_error_response({**data, "details": {"supportedVersions": [0, 1]}}), ERROR_RESPONSE)


def test_requirement_unmet_names_the_requirement_and_whats_wanted() -> None:
    # Spec: runner-protocol, "A runner refuses a platform it can't run on" (local-model-runner D16).
    data = {"code": "runner.requirement-unmet", "problem": "p", "fix": "f"}
    found = {"requirement": "ollama", "wanted": ">= 0.12.6", "found": "0.12.5"}
    assert not is_valid(_error_response(data), ERROR_RESPONSE, runner=None)
    response = _error_response({**data, "details": found})
    assert is_valid(response, ERROR_RESPONSE, runner=None)


def test_requirement_unmet_leaves_out_found_when_nothing_was_found() -> None:
    data = {"code": "runner.requirement-unmet", "problem": "p", "fix": "f"}
    details = {"requirement": "ollama", "wanted": ">= 0.12.6"}
    assert is_valid(_error_response({**data, "details": details}), ERROR_RESPONSE, runner=None)
    assert not is_valid(
        _error_response({**data, "details": {**details, "version": "x"}}),
        ERROR_RESPONSE,
        runner=None,
    )
    assert not is_valid(
        _error_response({**data, "details": {"requirement": "ollama"}}), ERROR_RESPONSE, runner=None
    )


def test_a_code_the_runner_has_not_published_does_not_validate_against_the_contract_alone() -> None:
    data = {
        "code": "scripted.invalid-script",
        "problem": "p",
        "fix": "f",
        "details": {"where": "options.script"},
    }
    assert not is_valid(_error_response(data), ERROR_RESPONSE, runner=None)
    validate(_error_response(data), ERROR_RESPONSE)  # with the scripted runner's codes bound


# Requirement: Run start options are an extension point


def test_the_contract_alone_accepts_only_empty_options() -> None:
    assert is_valid(_request("run/start", {**START, "options": {}}), "run-start.schema.json", None)
    assert not is_valid(_request("run/start", START), "run-start.schema.json", runner=None)


# Requirement: Run start carries everything the runner may use


def test_with_a_runners_schema_bound_its_options_validate_and_an_unknown_key_does_not() -> None:
    validate(_request("run/start", START), "run-start.schema.json")
    unknown = {**START, "options": {**START["options"], "speed": 2}}
    assert not is_valid(_request("run/start", unknown), "run-start.schema.json")


# Requirement: Run start's effects are always explicit (declared-effects)


def test_a_run_start_for_a_read_only_actor_validates_with_three_empty_lists() -> None:
    validate(_request("run/start", START), "run-start.schema.json")
    assert START["effects"] == {"write": [], "delete": [], "move": []}


@pytest.mark.parametrize("missing", ["write", "delete", "move"])
def test_a_run_start_whose_effects_lack_a_list_does_not_validate(missing: str) -> None:
    effects: dict[str, list[str]] = {
        key: [] for key in ("write", "delete", "move") if key != missing
    }
    assert not is_valid(
        _request("run/start", {**START, "effects": effects}), "run-start.schema.json"
    )


@pytest.mark.parametrize("field", ["effects", "scratch"])
def test_a_run_start_without_effects_or_scratch_does_not_validate(field: str) -> None:
    params = {key: value for key, value in START.items() if key != field}
    assert not is_valid(_request("run/start", params), "run-start.schema.json")


# Requirement: Run start says whether the run may compact (compaction-opt-in)


def test_a_run_start_without_on_context_full_does_not_validate() -> None:
    params = {key: value for key, value in START.items() if key != "onContextFull"}
    assert not is_valid(_request("run/start", params), "run-start.schema.json")


def test_a_run_start_with_an_on_context_full_off_the_list_does_not_validate() -> None:
    params = {**START, "onContextFull": "summarise"}
    assert not is_valid(_request("run/start", params), "run-start.schema.json")


@pytest.mark.parametrize("value", ["fail", "compact"])
def test_a_run_start_with_either_on_context_full_validates(value: str) -> None:
    assert is_valid(
        _request("run/start", {**START, "onContextFull": value}), "run-start.schema.json"
    )


@pytest.mark.parametrize("pattern", ["/abs/**", "../x", "a**", ".troupe/**", ".git/config", ""])
def test_a_run_start_with_a_malformed_pattern_does_not_validate(pattern: str) -> None:
    effects = {"write": [pattern], "delete": [], "move": []}
    assert not is_valid(
        _request("run/start", {**START, "effects": effects}), "run-start.schema.json"
    )


# Requirement: Init says how the runner applies the effects (declared-effects)


def _init(**fields: object) -> dict[str, Any]:
    event: dict[str, Any] = {
        "runId": RUN_ID,
        "seq": 0,
        "type": "init",
        "runner": {"name": "scripted", "version": "0.1.0"},
        "tools": [],
    }
    return {**event, **fields}


def test_an_init_event_without_effects_does_not_validate() -> None:
    assert not is_valid(_init(), "run-event.schema.json#/$defs/event")


@pytest.mark.parametrize("value", ["checked", "translated"])
def test_an_init_event_saying_how_effects_are_applied_validates(value: str) -> None:
    validate(_init(effects=value), "run-event.schema.json#/$defs/event")


def test_an_init_event_whose_effects_are_none_does_not_validate() -> None:
    assert not is_valid(_init(effects="none"), "run-event.schema.json#/$defs/event")


# Requirement: A run that uses kinds stores each record with its kind

STORED = "https://troupe.run/protocol/transcript-record.schema.json"


@pytest.mark.parametrize(
    "line",
    [
        {"kind": "sent", "record": '{"model":"m"}'},
        {"kind": "note", "record": "x"},
        {"kind": "received", "record": "AP8=", "encoding": "base64"},
    ],
)
def test_a_stored_transcript_line_validates(line: dict[str, Any]) -> None:
    validator_for(STORED).validate(line)


@pytest.mark.parametrize(
    "line",
    [
        {"kind": "sent", "record": "x", "encoding": "utf-8"},
        {"kind": "sent", "record": "x", "extra": 1},
        {"kind": "request", "record": "x"},
        {"record": "x"},
    ],
    ids=["utf-8 encoding", "extra key", "unknown kind", "no kind"],
)
def test_a_stored_transcript_line_that_breaks_the_form_does_not_validate(
    line: dict[str, Any],
) -> None:
    assert not validator_for(STORED).is_valid(line)
