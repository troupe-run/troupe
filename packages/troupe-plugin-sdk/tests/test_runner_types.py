"""The SDK's runner contract types agree with the schemas in protocol/schemas/runner/ (spec:
runner-protocol, plugin-sdk; runner-contract design D11; runner-sdk design D3)."""

import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from runner_schemas import is_valid, validate
from troupe_plugin_sdk import runner as p

RUN_IDS = st.uuids().map(str)
RUN = "0f8fad5b-d9cb-469f-a165-70867728950e"
TEXT = st.text(max_size=30)
NAME = st.text(min_size=1, max_size=20)
NAMED = st.fixed_dictionaries({"name": NAME, "version": NAME})


def _with_optional(
    required: dict[str, st.SearchStrategy[Any]], optional: dict[str, st.SearchStrategy[Any]]
) -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(required, optional=optional)


def _event(
    type_: str,
    seq: st.SearchStrategy[int],
    required: dict[str, st.SearchStrategy[Any]] | None = None,
    optional: dict[str, st.SearchStrategy[Any]] | None = None,
) -> st.SearchStrategy[Any]:
    required, optional = required or {}, optional or {}
    return _with_optional(
        {"runId": RUN_IDS, "seq": seq, "type": st.just(type_), **required}, optional
    )


SEQ = st.integers(min_value=1, max_value=10**9)


def _with_reason_when_failed(data: dict[str, Any]) -> st.SearchStrategy[Any]:
    """An error result always has a reason, and an ok result never does."""
    if data["status"] == "ok":
        return st.just(data)
    return st.sampled_from(p.FAILURE_REASONS).map(lambda reason: {**data, "reason": reason})


# (type, schema reference, strategy for valid JSON data of that type)
CASES: list[tuple[type[p.Message], str, st.SearchStrategy[Any]]] = [
    (
        p.InitializeParams,
        "initialize.schema.json#/properties/params",
        st.fixed_dictionaries(
            {
                "protocolVersions": st.lists(st.integers(0, 9), min_size=1, unique=True),
                "host": NAMED,
                "capabilities": st.lists(NAME, unique=True, max_size=3),
            }
        ),
    ),
    (
        p.InitializeResult,
        "initialize.schema.json#/$defs/result",
        st.fixed_dictionaries(
            {
                "protocolVersion": st.integers(0, 9),
                "runner": NAMED,
                "capabilities": st.lists(NAME, unique=True, max_size=3),
            }
        ),
    ),
    (
        p.RunStartParams,
        "run-start.schema.json#/properties/params",
        st.fixed_dictionaries(
            {
                "runId": RUN_IDS,
                "direction": TEXT,
                "workspace": NAME,
                "options": st.fixed_dictionaries(
                    {"script": st.fixed_dictionaries({"steps": st.just([])})},
                    optional={"replayDelays": st.booleans()},
                ),
                "limits": st.fixed_dictionaries({"eventMaxBytes": st.integers(1, 10**9)}),
                "effects": st.fixed_dictionaries(
                    {
                        "write": st.lists(st.sampled_from(["out/**", "a.txt", "**"]), max_size=2),
                        "delete": st.lists(st.sampled_from(["drafts/*", "x?"]), max_size=2),
                        "move": st.lists(st.sampled_from(["docs/**/*.md"]), max_size=1),
                    }
                ),
                "scratch": NAME,
            }
        ),
    ),
    (
        p.RunStartResult,
        "run-start.schema.json#/$defs/result",
        st.fixed_dictionaries({"runId": RUN_IDS}),
    ),
    (
        p.RunCancelParams,
        "run-cancel.schema.json#/properties/params",
        st.fixed_dictionaries({"runId": RUN_IDS}),
    ),
    (p.Empty, "shutdown.schema.json#/$defs/result", st.just({})),
    (
        p.InitEvent,
        "run-event.schema.json#/$defs/init",
        _event(
            "init",
            st.just(0),
            required={
                "runner": NAMED,
                "effects": st.sampled_from(["checked", "translated"]),
                "tools": st.lists(NAME, max_size=3),
            },
            optional={
                "engine": _with_optional({"name": NAME}, {"version": NAME, "model": NAME}),
            },
        ),
    ),
    (
        p.TurnEvent,
        "run-event.schema.json#/$defs/turn",
        _event(
            "turn",
            SEQ,
            required={"role": st.sampled_from(["assistant", "user"]), "text": TEXT},
        ),
    ),
    (
        p.ToolCallEvent,
        "run-event.schema.json#/$defs/tool_call",
        _event(
            "tool_call",
            SEQ,
            required={"callId": NAME, "tool": NAME, "inputSummary": TEXT},
        ),
    ),
    (
        p.ToolResultEvent,
        "run-event.schema.json#/$defs/tool_result",
        _event(
            "tool_result",
            SEQ,
            required={
                "callId": NAME,
                "isError": st.booleans(),
                "outputSummary": TEXT,
                "outputBytes": st.integers(0, 10**12),
            },
        ),
    ),
    (
        p.RetryEvent,
        "run-event.schema.json#/$defs/retry",
        _event(
            "retry",
            SEQ,
            required={
                "attempt": st.integers(1, 99),
                "delayMs": st.integers(0, 10**6),
                "reason": st.sampled_from(
                    ["authentication", "rate-limit", "network", "server", "other"]
                ),
            },
            optional={"maxAttempts": st.integers(1, 99), "message": TEXT},
        ),
    ),
    (
        p.LogEvent,
        "run-event.schema.json#/$defs/log",
        _event(
            "log",
            SEQ,
            required={
                "level": st.sampled_from(["debug", "info", "warning", "error"]),
                "message": TEXT,
            },
        ),
    ),
    (
        p.ResultEvent,
        "run-event.schema.json#/$defs/result",
        _event(
            "result",
            SEQ,
            required={"status": st.sampled_from(["ok", "error"]), "message": TEXT},
            optional={
                "turns": st.integers(0, 999),
                "durationMs": st.integers(0, 10**9),
                "usage": _with_optional(
                    {},
                    {
                        key: st.integers(0, 10**9)
                        for key in (
                            "inputTokens",
                            "outputTokens",
                            "cacheReadTokens",
                            "cacheWriteTokens",
                        )
                    },
                ),
                "costUsd": st.floats(0, 1000, allow_nan=False),
            },
        ).flatmap(_with_reason_when_failed),
    ),
    (
        p.OversizedEvent,
        "run-event.schema.json#/$defs/oversized",
        _event(
            "oversized",
            SEQ,
            required={
                "originalType": st.sampled_from(sorted(p.EVENT_TYPES)),
                "bytes": st.integers(1, 10**9),
                "ref": st.from_regex(r"\Asha256:[0-9a-f]{64}\Z"),
            },
        ),
    ),
    (
        p.TranscriptRecord,
        "run-transcript.schema.json#/properties/params",
        _with_optional(
            {"runId": RUN_IDS, "record": TEXT},
            {"encoding": st.sampled_from(["utf-8", "base64"])},
        ),
    ),
    (
        p.ErrorData,
        "errors.schema.json#/$defs/anyError",
        _with_optional(
            {
                "code": st.sampled_from(["runner.invalid-params", "runner.already-started"]),
                "problem": NAME,
                "fix": NAME,
            },
            {"path": NAME},
        )
        | _with_optional(
            {
                "code": st.just("runner.unsupported-version"),
                "problem": NAME,
                "fix": NAME,
                "details": st.fixed_dictionaries(
                    {"supportedVersions": st.lists(st.integers(0, 9), min_size=1, unique=True)}
                ),
            },
            {"path": NAME},
        )
        | _with_optional(
            {
                "code": st.just("runner.requirement-unmet"),
                "problem": NAME,
                "fix": NAME,
                "details": _with_optional(
                    {"requirement": NAME, "wanted": NAME}, {"found": st.text(max_size=8)}
                ),
            },
            {"path": NAME},
        )
        | st.fixed_dictionaries(
            {
                "code": st.sampled_from(["scripted.invalid-script", "scripted.unknown-option"]),
                "problem": NAME,
                "fix": NAME,
                "details": st.fixed_dictionaries({"where": NAME}),
            }
        ),
    ),
]


@pytest.mark.parametrize(("cls", "ref", "data"), CASES, ids=[case[0].__name__ for case in CASES])
@settings(max_examples=40, deadline=None)
@given(st.data())
def test_each_type_reads_and_writes_exactly_the_schemas_json(
    cls: type[p.Message], ref: str, data: st.SearchStrategy[Any], draw: st.DataObject
) -> None:
    raw = draw.draw(data)
    validate(raw, ref)  # the strategy produces only schema-valid data
    message = cls.from_data(raw)
    written = message.to_data()
    assert written == raw
    validate(written, ref)
    assert cls.from_data(json.loads(json.dumps(written))) == message


def test_every_runner_event_type_has_a_python_type() -> None:
    covered = {case[0].TYPE for case in CASES if issubclass(case[0], p.RunEvent)}
    assert covered == {*p.EVENT_TYPES, "oversized"}


# Strictness: what the schema refuses, from_data refuses too

INIT = {
    "runId": RUN,
    "seq": 0,
    "type": "init",
    "runner": {"name": "s", "version": "1"},
    "effects": "checked",
    "tools": [],
}

REFUSED: list[tuple[str, type[p.Message], dict[str, Any], str]] = [
    ("unknown field", p.InitEvent, {**INIT, "colour": "red"}, "unknown field"),
    (
        "unknown field on tool_call",
        p.ToolCallEvent,
        {
            "runId": RUN,
            "seq": 1,
            "type": "tool_call",
            "callId": "c1",
            "tool": "Read",
            "inputSummary": "{}",
            "input": {},
        },
        "ToolCallEvent: unknown field\\(s\\) 'input'",
    ),
    (
        "native on init",
        p.InitEvent,
        {**INIT, "native": {"type": "system", "subtype": "init"}},
        "unknown field",
    ),
    (
        "unnamed usage counter",
        p.ResultEvent,
        {
            "runId": RUN,
            "seq": 1,
            "type": "result",
            "status": "ok",
            "message": "",
            "usage": {"reasoningTokens": 3},
        },
        "unknown field",
    ),
    ("missing field", p.InitEvent, {k: v for k, v in INIT.items() if k != "tools"}, "missing"),
    ("wrong type", p.InitEvent, {**INIT, "tools": "Write"}, "must be an array"),
    ("init not first", p.InitEvent, {**INIT, "seq": 3}, "seq is always 0"),
    ("bad run id", p.InitEvent, {**INIT, "runId": "has space"}, "doesn't match"),
    ("uppercase uuid", p.InitEvent, {**INIT, "runId": RUN.upper()}, "doesn't match"),
    (
        "bool as int",
        p.RetryEvent,
        {"runId": RUN, "seq": 1, "type": "retry", "attempt": True, "delayMs": 0, "reason": "other"},
        "must be an integer",
    ),
    (
        "negative",
        p.ToolResultEvent,
        {
            "runId": RUN,
            "seq": 1,
            "type": "tool_result",
            "callId": "c",
            "isError": False,
            "outputSummary": "",
            "outputBytes": -1,
        },
        "at least 0",
    ),
    (
        "error result without a reason",
        p.ResultEvent,
        {"runId": RUN, "seq": 1, "type": "result", "status": "error", "message": ""},
        "ResultEvent: an error result needs a reason",
    ),
    (
        "ok result with a reason",
        p.ResultEvent,
        {
            "runId": RUN,
            "seq": 1,
            "type": "result",
            "status": "ok",
            "message": "",
            "reason": "budget",
        },
        "ResultEvent: an ok result has no reason",
    ),
    (
        "reason off the list",
        p.ResultEvent,
        {
            "runId": RUN,
            "seq": 1,
            "type": "result",
            "status": "error",
            "message": "",
            "reason": "timeout",
        },
        "one of",
    ),
    (
        "bad enum",
        p.ResultEvent,
        {"runId": RUN, "seq": 1, "type": "result", "status": "success", "message": ""},
        "one of",
    ),
    ("wrong type field", p.TurnEvent, {**INIT, "type": "init"}, "type must be 'turn'"),
    (
        "no versions",
        p.InitializeParams,
        {"protocolVersions": [], "host": {"name": "t", "version": "1"}, "capabilities": []},
        "at least 1",
    ),
]


@pytest.mark.parametrize(("_", "cls", "data", "match"), REFUSED, ids=[r[0] for r in REFUSED])
def test_from_data_refuses_what_the_schema_refuses(
    _: str, cls: type[p.Message], data: dict[str, Any], match: str
) -> None:
    ref = {
        p.InitEvent: "run-event.schema.json#/$defs/init",
        p.RetryEvent: "run-event.schema.json#/$defs/retry",
        p.ToolCallEvent: "run-event.schema.json#/$defs/tool_call",
        p.ToolResultEvent: "run-event.schema.json#/$defs/tool_result",
        p.ResultEvent: "run-event.schema.json#/$defs/result",
        p.TurnEvent: "run-event.schema.json#/$defs/turn",
        p.InitializeParams: "initialize.schema.json#/properties/params",
    }[cls]
    assert not is_valid(data, ref)
    with pytest.raises(p.ProtocolError, match=match):
        cls.from_data(data)


def test_parse_event_dispatches_on_type_and_refuses_troupes_own_oversized_event() -> None:
    assert isinstance(p.parse_event(INIT), p.InitEvent)
    oversized = {
        "runId": RUN,
        "seq": 1,
        "type": "oversized",
        "originalType": "log",
        "bytes": 9,
        "ref": "sha256:" + "0" * 64,
    }
    with pytest.raises(p.ProtocolError, match="unknown event type 'oversized'"):
        p.parse_event(oversized)
    with pytest.raises(p.ProtocolError, match="unknown event type"):
        p.parse_event({"type": "thought"})


# Reading lines from a runner


def test_parse_line_sorts_notifications_and_responses() -> None:
    note = p.parse_line(b'{"jsonrpc":"2.0","method":"run/event","params":{"a":1}}\n')
    assert (note.method, note.params) == ("run/event", {"a": 1})
    ok = p.parse_line(b'{"jsonrpc":"2.0","id":3,"result":{}}')
    assert (ok.id, ok.result) == (3, {})
    error = p.parse_line(
        b'{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"m",'
        b'"data":{"code":"runner.parse","problem":"p","fix":"f"}}}'
    )
    assert error.error is not None
    assert error.error.data.code == "runner.parse"


@pytest.mark.parametrize(
    "line",
    [
        b"not json at all",
        b"\xff\xfe",
        b"[1, 2]",
        b'{"jsonrpc":"1.0","method":"x","params":{}}',
        b'{"jsonrpc":"2.0","id":1,"method":"run/start","params":{}}',
        b'{"jsonrpc":"2.0","id":true,"result":{}}',
        b'{"jsonrpc":"2.0","id":1,"result":[]}',
        b'{"jsonrpc":"2.0","id":1,"error":{"code":1,"message":"no data"}}',
    ],
)
def test_parse_line_refuses_anything_a_runner_may_not_send(line: bytes) -> None:
    with pytest.raises(p.ProtocolError):
        p.parse_line(line)


def test_messages_the_host_builds_validate_as_host_messages() -> None:
    sent = [
        p.request(1, "initialize", p.InitializeParams([0], p.Named("troupe", "0.0.1"), [])),
        p.request(
            2,
            "run/start",
            p.RunStartParams(
                RUN,
                "go",
                "/w",
                {"script": {"steps": []}},
                p.StartLimits(65536),
                p.READ_ONLY_DECLARATION,
                "/s",
            ),
        ),
        p.request(3, "run/cancel", p.RunCancelParams(RUN)),
        p.request(4, "shutdown", p.Empty()),
    ]
    for message in sent:
        validate(message, "message.schema.json#/$defs/fromHost")


# Ambiguous JSON is refused, never read with a guess (design D1a)


@pytest.mark.parametrize(
    "line",
    [
        b'{"jsonrpc":"2.0","method":"run/event","method":"run/transcript","params":{}}',
        b'{"jsonrpc":"2.0","method":"run/event","params":{"seq":1,"seq":2}}',
        b'{"jsonrpc":"2.0","method":"run/event","params":{"costUsd":NaN}}',
        b'{"jsonrpc":"2.0","method":"run/event","params":{"costUsd":Infinity}}',
        b'{"jsonrpc":"2.0","method":"run/event","params":{"costUsd":-Infinity}}',
    ],
    ids=["duplicate top-level key", "duplicate nested key", "NaN", "Infinity", "-Infinity"],
)
def test_parse_line_refuses_ambiguous_json(line: bytes) -> None:
    with pytest.raises(p.ProtocolError, match=r"ambiguous JSON|isn't a JSON number"):
        p.parse_line(line)


def test_parse_line_reads_a_message_ending_in_a_carriage_return_and_line_feed() -> None:
    note = p.parse_line(b'{"jsonrpc":"2.0","method":"run/event","params":{}}\r\n')
    assert note.method == "run/event"


# Requirement: Init says how the runner applies the effects (declared-effects): a runner must send
# it, and an init troupe recorded before it existed still reads.


def test_a_runner_sent_init_without_effects_is_refused_naming_it() -> None:
    legacy = {key: value for key, value in INIT.items() if key != "effects"}
    with pytest.raises(p.ProtocolError, match="InitEvent: missing required field 'effects'"):
        p.parse_event(legacy)
    assert not is_valid(legacy, "run-event.schema.json#/$defs/event")


def test_an_init_recorded_before_effects_existed_still_reads_as_a_host_event() -> None:
    legacy = {key: value for key, value in INIT.items() if key != "effects"}
    event = p.InitEvent.from_data(legacy)
    assert event.effects is None
    validate(legacy, "run-event.schema.json#/$defs/hostEvent")


# Requirement: The SDK's result type carries the reason


def test_a_runner_cant_build_an_error_result_without_a_reason() -> None:
    with pytest.raises(p.ProtocolError, match=r"ResultEvent: an error result needs a reason"):
        p.ResultEvent(run_id=RUN, seq=1, status="error", message="401")


def test_a_runner_cant_build_an_ok_result_with_a_reason() -> None:
    with pytest.raises(p.ProtocolError, match=r"ResultEvent: an ok result has no reason"):
        p.ResultEvent(run_id=RUN, seq=1, status="ok", message="done", reason="budget")


def test_the_host_parsing_an_error_result_without_a_reason_refuses_it_naming_reason() -> None:
    data = {"runId": RUN, "seq": 1, "type": "result", "status": "error", "message": "401"}
    with pytest.raises(p.ProtocolError, match=r"ResultEvent: .*reason"):
        p.parse_event(data)


def test_an_error_result_with_a_reason_round_trips() -> None:
    event = p.ResultEvent(run_id=RUN, seq=1, status="error", message="401", reason="authentication")
    assert event.to_data()["reason"] == "authentication"
    assert p.parse_event(event.to_data()) == event
