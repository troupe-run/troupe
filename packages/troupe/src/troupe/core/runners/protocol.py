"""The runner contract's messages as Python types (spec: runner-protocol; design D2, D3, D11).

The JSON Schemas in protocol/schemas/runner/ are the source of truth (decision #7). These types
mirror them by hand until a generator is chosen, and the tests check every type against the
schemas.

``from_data`` is strict, like the schemas: an unknown field, a missing required field, a wrong type
or a value out of range raises ProtocolError, which the host treats as a protocol violation.
``to_data`` produces the JSON shape, leaving out optional fields that are absent.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

# Message and ProtocolError are re-exported: callers know them as part of the runner contract.
from troupe.core.messages import Message as Message
from troupe.core.messages import ProtocolError as ProtocolError
from troupe.core.messages import fail, json_field

PROTOCOL_VERSION = 0
"""The protocol version this troupe speaks. Version 0 is the draft contract: it changes in place,
with no compatibility promise, until troupe commits to version 1 (strict-schemas design D9)."""

RUN_ID_PATTERN = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
"""Run ids are UUIDs in canonical lowercase form (design D11)."""
REF_PATTERN = re.compile(r"\Asha256:[0-9a-f]{64}\Z")

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_REFUSED = -32000
"""The application error code for a valid request the runner refuses (design D2)."""


# The handshake


@dataclass(frozen=True)
class Named(Message):
    name: str = json_field("name", min_length=1)
    version: str = json_field("version", min_length=1)


@dataclass(frozen=True)
class InitializeParams(Message):
    protocol_versions: list[int] = json_field("protocolVersions", min_items=1, unique=True)
    host: Named = json_field("host")
    capabilities: list[str] = json_field("capabilities", unique=True)

    def _check(self, where: str) -> None:
        if any(version < 0 for version in self.protocol_versions):
            raise fail(where, "protocol versions start at 0")
        if any(not name for name in self.capabilities):
            raise fail(where, "capability names must not be empty")


@dataclass(frozen=True)
class InitializeResult(Message):
    protocol_version: int = json_field("protocolVersion", minimum=0)
    runner: Named = json_field("runner")
    capabilities: list[str] = json_field("capabilities", unique=True)

    def _check(self, where: str) -> None:
        if any(not name for name in self.capabilities):
            raise fail(where, "capability names must not be empty")


# Starting, cancelling and shutting down


@dataclass(frozen=True)
class StartLimits(Message):
    event_max_bytes: int = json_field("eventMaxBytes", minimum=1)


@dataclass(frozen=True)
class RunStartParams(Message):
    run_id: str = json_field("runId", pattern=RUN_ID_PATTERN)
    direction: str = json_field("direction")
    workspace: str = json_field("workspace", min_length=1)
    options: dict[str, object] = json_field("options")
    limits: StartLimits = json_field("limits")
    character: str | None = json_field("character", default=None)


@dataclass(frozen=True)
class RunStartResult(Message):
    run_id: str = json_field("runId", pattern=RUN_ID_PATTERN)


@dataclass(frozen=True)
class RunCancelParams(Message):
    run_id: str = json_field("runId", pattern=RUN_ID_PATTERN)


@dataclass(frozen=True)
class Empty(Message):
    """The params of shutdown, and the result of run/cancel and shutdown."""


# Run events


@dataclass(frozen=True)
class Engine(Message):
    name: str = json_field("name", min_length=1)
    version: str | None = json_field("version", default=None, min_length=1)
    model: str | None = json_field("model", default=None, min_length=1)


@dataclass(frozen=True)
class Usage(Message):
    """Token counts, where the engine reports them."""

    input_tokens: int | None = json_field("inputTokens", default=None, minimum=0)
    output_tokens: int | None = json_field("outputTokens", default=None, minimum=0)
    cache_read_tokens: int | None = json_field("cacheReadTokens", default=None, minimum=0)
    cache_write_tokens: int | None = json_field("cacheWriteTokens", default=None, minimum=0)


@dataclass(frozen=True)
class RunEvent(Message):
    """Every run event: the run id, its seq, and (as TYPE) its type."""

    run_id: str = json_field("runId", pattern=RUN_ID_PATTERN)
    seq: int = json_field("seq", minimum=0)


@dataclass(frozen=True)
class InitEvent(RunEvent):
    TYPE: ClassVar[str | None] = "init"
    runner: Named = json_field("runner")
    tools: list[str] = json_field("tools")
    engine: Engine | None = json_field("engine", default=None)

    def _check(self, where: str) -> None:
        if self.seq != 0:
            raise fail(where, f"an init event's seq is always 0, not {self.seq}")
        if any(not tool for tool in self.tools):
            raise fail(where, "tool names must not be empty")


@dataclass(frozen=True)
class TurnEvent(RunEvent):
    TYPE: ClassVar[str | None] = "turn"
    role: Literal["assistant", "user"] = json_field("role")
    text: str = json_field("text")


@dataclass(frozen=True)
class ToolCallEvent(RunEvent):
    TYPE: ClassVar[str | None] = "tool_call"
    call_id: str = json_field("callId", min_length=1)
    tool: str = json_field("tool", min_length=1)
    input_summary: str = json_field("inputSummary")


@dataclass(frozen=True)
class ToolResultEvent(RunEvent):
    TYPE: ClassVar[str | None] = "tool_result"
    call_id: str = json_field("callId", min_length=1)
    is_error: bool = json_field("isError")
    output_summary: str = json_field("outputSummary")
    output_bytes: int = json_field("outputBytes", minimum=0)


RetryReason = Literal["authentication", "rate-limit", "network", "server", "other"]


@dataclass(frozen=True)
class RetryEvent(RunEvent):
    TYPE: ClassVar[str | None] = "retry"
    attempt: int = json_field("attempt", minimum=1)
    delay_ms: int = json_field("delayMs", minimum=0)
    reason: RetryReason = json_field("reason")
    max_attempts: int | None = json_field("maxAttempts", default=None, minimum=1)
    message: str | None = json_field("message", default=None)


@dataclass(frozen=True)
class LogEvent(RunEvent):
    TYPE: ClassVar[str | None] = "log"
    level: Literal["debug", "info", "warning", "error"] = json_field("level")
    message: str = json_field("message")


@dataclass(frozen=True)
class ResultEvent(RunEvent):
    TYPE: ClassVar[str | None] = "result"
    status: Literal["ok", "error"] = json_field("status")
    message: str = json_field("message")
    turns: int | None = json_field("turns", default=None, minimum=0)
    duration_ms: int | None = json_field("durationMs", default=None, minimum=0)
    usage: Usage | None = json_field("usage", default=None)
    cost_usd: float | None = json_field("costUsd", default=None, minimum=0)


EventType = Literal["init", "turn", "tool_call", "tool_result", "retry", "log", "result"]


@dataclass(frozen=True)
class OversizedEvent(RunEvent):
    """Written by troupe in place of an event over the maximum size; never sent by a runner."""

    TYPE: ClassVar[str | None] = "oversized"
    original_type: EventType = json_field("originalType")
    bytes: int = json_field("bytes", minimum=1)
    ref: str = json_field("ref", pattern=REF_PATTERN)


EVENT_TYPES: dict[str, type[RunEvent]] = {
    cls.TYPE: cls
    for cls in (
        InitEvent,
        TurnEvent,
        ToolCallEvent,
        ToolResultEvent,
        RetryEvent,
        LogEvent,
        ResultEvent,
    )
    if cls.TYPE is not None
}
"""The event types a runner may send, by their ``type``."""


def parse_event(data: object) -> RunEvent:
    """A run event sent by a runner. ``oversized`` is troupe's own and is refused here."""
    if not isinstance(data, dict):
        raise fail("run event", "must be an object")
    kind = data.get("type")
    if not isinstance(kind, str) or kind not in EVENT_TYPES:
        raise fail("run event", f"unknown event type {kind!r}")
    return EVENT_TYPES[kind].from_data(data)


@dataclass(frozen=True)
class TranscriptRecord(Message):
    run_id: str = json_field("runId", pattern=RUN_ID_PATTERN)
    record: str = json_field("record")
    encoding: Literal["utf-8", "base64"] | None = json_field("encoding", default=None)


# Errors and JSON-RPC envelopes


@dataclass(frozen=True)
class ErrorData(Message):
    """troupe's structured error (protocol/schemas/error.schema.json) carried in an error's data."""

    code: str = json_field("code", pattern=re.compile(r"\A[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+\Z"))
    problem: str = json_field("problem", min_length=1)
    fix: str = json_field("fix", min_length=1)
    path: str | None = json_field("path", default=None, min_length=1)
    details: dict[str, object] | None = json_field("details", default=None)


@dataclass(frozen=True)
class RpcError(Message):
    code: int = json_field("code")
    message: str = json_field("message", min_length=1)
    data: ErrorData = json_field("data")


def request(id_: int, method: str, params: Message) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params.to_data()}


def notification(method: str, params: Message) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params.to_data()}


def success(id_: int | str, result: Message) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result.to_data()}


@dataclass(frozen=True)
class Incoming:
    """One message from a runner, sorted by kind. Exactly one of the three groups is set."""

    method: str | None = None
    params: object = None
    id: int | str | None = None
    result: dict[str, Any] | None = None
    error: RpcError | None = None


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ProtocolError(f"ambiguous JSON: the key {key!r} appears more than once")
        data[key] = value
    return data


def _no_non_finite(constant: str) -> object:
    raise ProtocolError(f"not JSON: {constant} isn't a JSON number")


def loads_strict(line: bytes) -> object:
    """Parse one line of JSON, refusing what Python's reader would quietly accept (design D1a):
    a duplicated key (it would keep the last value) and NaN or Infinity (not JSON)."""
    try:
        return json.loads(line, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_non_finite)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(f"not JSON: {error}") from error


def parse_line(line: bytes) -> Incoming:
    """Read one line a runner wrote: a notification, a success response or an error response."""
    data = loads_strict(line)
    if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
        raise ProtocolError("not a JSON-RPC 2.0 message")
    keys = set(data) - {"jsonrpc"}
    if keys == {"method", "params"}:
        if not isinstance(data["method"], str):
            raise ProtocolError("a notification's method must be a string")
        return Incoming(method=data["method"], params=data["params"])
    if keys == {"id", "result"}:
        if not isinstance(data["id"], int | str) or isinstance(data["id"], bool):
            raise ProtocolError("a response's id must be an integer or a string")
        if not isinstance(data["result"], dict):
            raise ProtocolError("a response's result must be an object")
        return Incoming(id=data["id"], result=data["result"])
    if keys == {"id", "error"}:
        id_ = data["id"]
        if id_ is not None and (not isinstance(id_, int | str) or isinstance(id_, bool)):
            raise ProtocolError("an error response's id must be an integer, a string or null")
        return Incoming(id=id_, error=RpcError.from_data(data["error"]))
    raise ProtocolError(
        "not a notification or a response that a runner may send "
        f"(fields: {', '.join(sorted(keys))})"
    )
