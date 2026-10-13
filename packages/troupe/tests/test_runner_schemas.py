"""Tests for the runner contract's schemas (spec: runner-protocol)."""

from collections.abc import Iterator
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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


START = {
    "runId": RUN_ID,
    "instructions": "write hello.txt",
    "workspace": "/workspace",
    "options": {"anything": ["goes", 1]},
    "limits": {"eventMaxBytes": 65536},
}

ERROR_DATA = {
    "code": "runner.unsupported-version",
    "problem": "p",
    "fix": "f",
    "details": {"supportedVersions": [1]},
}

# (schema, a valid example, an invalid example)
EXAMPLES: list[tuple[str, object, object]] = [
    (
        "initialize.schema.json",
        _request(
            "initialize",
            {
                "protocolVersions": [1],
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
            "protocolVersion": 1,
            "runner": {"name": "scripted", "version": "0.1"},
            "capabilities": ["resume"],
        },
        {
            "protocolVersion": 1,
            "runner": {"name": "scripted", "version": "0.1"},
            "capabilities": ["resume", "resume"],
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


EVENTS: dict[str, dict[str, Any]] = {
    "init": {
        "runner": {"name": "s", "version": "1"},
        "tools": ["Write"],
        "engine": {"name": "claude-code", "version": "2.1.281", "model": "m"},
    },
    "turn": {"role": "assistant", "text": "hello"},
    "tool_call": {"callId": "c1", "tool": "Write", "inputSummary": "out/hello.txt"},
    "tool_result": {"callId": "c1", "isError": False, "outputSummary": "ok", "outputBytes": 2},
    "retry": {"attempt": 1, "maxAttempts": 10, "delayMs": 500, "reason": "authentication"},
    "log": {"level": "info", "message": "starting"},
    "result": {
        "status": "error",
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


def test_a_usage_counter_the_contract_doesnt_name_is_refused() -> None:
    event = {"runId": RUN_ID, "seq": 3, "type": "result", **EVENTS["result"]}
    event["usage"] = {"reasoningTokens": 2}
    assert not is_valid(event, "run-event.schema.json#/$defs/event")


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
            {field: _strategy(schema["properties"][field]) for field in schema["required"]}
        )
        for schema in _event_defs().values()
    ]
    return st.one_of(choices)


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


# Requirement: A success result matches its method's result schema

SUCCESS = "jsonrpc.schema.json#/$defs/successResponse"


@pytest.mark.parametrize(
    "result",
    [
        {"protocolVersion": 1, "runner": {"name": "s", "version": "1"}, "capabilities": []},
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
    validate(_error_response({**data, "details": {"supportedVersions": [1, 2]}}), ERROR_RESPONSE)


def test_a_code_the_runner_has_not_published_does_not_validate_against_the_contract_alone() -> None:
    data = {
        "code": "scripted.invalid-script",
        "problem": "p",
        "fix": "f",
        "details": {"where": "options.script"},
    }
    assert not is_valid(_error_response(data), ERROR_RESPONSE)
