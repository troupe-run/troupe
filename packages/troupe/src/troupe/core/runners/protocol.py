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
import types
import typing
from collections.abc import Mapping
from dataclasses import MISSING, dataclass, field, fields
from typing import Any, ClassVar, Literal, Self, get_args, get_origin, get_type_hints

PROTOCOL_VERSION = 1
"""The protocol version this troupe speaks."""

RUN_ID_PATTERN = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
"""Run ids are UUIDs in canonical lowercase form (design D11)."""
REF_PATTERN = re.compile(r"\Asha256:[0-9a-f]{64}\Z")

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_REFUSED = -32000
"""The application error code for a valid request the runner refuses (design D2)."""


class ProtocolError(ValueError):
    """A message that breaks the runner contract."""


def _json(
    name: str,
    *,
    default: object = MISSING,
    min_length: int | None = None,
    minimum: int | None = None,
    pattern: re.Pattern[str] | None = None,
    min_items: int | None = None,
    unique: bool = False,
) -> Any:  # noqa: ANN401 - dataclasses.field returns Any
    metadata = {
        "json": name,
        "min_length": min_length,
        "minimum": minimum,
        "pattern": pattern,
        "min_items": min_items,
        "unique": unique,
    }
    if default is MISSING:
        return field(metadata=metadata)
    return field(default=default, metadata=metadata)


def _fail(where: str, problem: str) -> ProtocolError:
    return ProtocolError(f"{where}: {problem}")


def _decode(value: object, hint: object, where: str, meta: Mapping[str, Any]) -> object:
    origin = get_origin(hint)
    if origin in (types.UnionType, typing.Union):
        (inner,) = [arg for arg in get_args(hint) if arg is not type(None)]
        return _decode(value, inner, where, meta)
    if origin is Literal:
        if value not in get_args(hint) or isinstance(value, bool):
            allowed = ", ".join(repr(arg) for arg in get_args(hint))
            raise _fail(where, f"must be one of {allowed}, not {value!r}")
        return value
    if hint is str:
        if not isinstance(value, str):
            raise _fail(where, f"must be a string, not {type(value).__name__}")
        if meta.get("min_length") is not None and len(value) < meta["min_length"]:
            raise _fail(where, "must not be empty")
        if meta.get("pattern") is not None and not meta["pattern"].match(value):
            raise _fail(where, f"{value!r} doesn't match {meta['pattern'].pattern}")
        return value
    if hint is bool:
        if not isinstance(value, bool):
            raise _fail(where, f"must be true or false, not {value!r}")
        return value
    if hint is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise _fail(where, f"must be an integer, not {value!r}")
        if meta.get("minimum") is not None and value < meta["minimum"]:
            raise _fail(where, f"must be at least {meta['minimum']}, not {value}")
        return value
    if hint is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise _fail(where, f"must be a number, not {value!r}")
        if meta.get("minimum") is not None and value < meta["minimum"]:
            raise _fail(where, f"must be at least {meta['minimum']}, not {value}")
        return float(value)
    if origin is list:
        (item,) = get_args(hint)
        if not isinstance(value, list):
            raise _fail(where, "must be an array")
        if meta.get("min_items") is not None and len(value) < meta["min_items"]:
            raise _fail(where, f"must have at least {meta['min_items']} item(s)")
        decoded = [_decode(entry, item, f"{where}[{i}]", {}) for i, entry in enumerate(value)]
        if meta.get("unique") and len({json.dumps(v) for v in decoded}) != len(decoded):
            raise _fail(where, "must not repeat an item")
        return decoded
    if origin is dict:
        _, item = get_args(hint)
        if not isinstance(value, dict):
            raise _fail(where, "must be an object")
        if item is object:
            return dict(value)
        return {
            key: _decode(entry, item, f"{where}.{key}", {"minimum": meta.get("minimum")})
            for key, entry in value.items()
        }
    if isinstance(hint, type) and issubclass(hint, Message):
        return hint._decode(value, where)
    raise TypeError(f"no decoder for {hint!r}")  # a bug in this module, not in the message


def _encode(value: object) -> object:
    if isinstance(value, Message):
        return value.to_data()
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value


_HINTS: dict[type, dict[str, Any]] = {}


def _hints(cls: type) -> dict[str, Any]:
    if cls not in _HINTS:
        _HINTS[cls] = get_type_hints(cls)
    return _HINTS[cls]


@dataclass(frozen=True)
class Message:
    """Base for every JSON object of the contract."""

    TYPE: ClassVar[str | None] = None
    """For run events: the value of the ``type`` field."""

    @classmethod
    def from_data(cls, data: object) -> Self:
        return cls._decode(data, cls.__name__)

    @classmethod
    def _decode(cls, data: object, where: str) -> Self:
        if not isinstance(data, dict):
            raise _fail(where, "must be an object")
        hints = _hints(cls)
        known = {f.metadata["json"] for f in fields(cls)}
        if cls.TYPE is not None:
            known.add("type")
            if data.get("type") != cls.TYPE:
                raise _fail(where, f"type must be {cls.TYPE!r}")
        unknown = sorted(set(data) - known)
        if unknown:
            raise _fail(where, f"unknown field(s) {', '.join(map(repr, unknown))}")
        values: dict[str, object] = {}
        for f in fields(cls):
            name = f.metadata["json"]
            if name not in data:
                if f.default is MISSING:
                    raise _fail(where, f"missing required field {name!r}")
                continue
            values[f.name] = _decode(data[name], hints[f.name], f"{where}.{name}", f.metadata)
        instance = cls(**values)
        instance._check(where)
        return instance

    def _check(self, where: str) -> None:
        """Rules beyond a single field's shape. Raise ProtocolError when broken."""

    def to_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.TYPE is not None:
            data["type"] = self.TYPE
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None and f.default is None:
                continue
            data[f.metadata["json"]] = _encode(value)
        return data


# The handshake


@dataclass(frozen=True)
class Named(Message):
    name: str = _json("name", min_length=1)
    version: str = _json("version", min_length=1)


@dataclass(frozen=True)
class InitializeParams(Message):
    protocol_versions: list[int] = _json("protocolVersions", min_items=1, unique=True)
    host: Named = _json("host")
    capabilities: list[str] = _json("capabilities", unique=True)

    def _check(self, where: str) -> None:
        if any(version < 1 for version in self.protocol_versions):
            raise _fail(where, "protocol versions start at 1")
        if any(not name for name in self.capabilities):
            raise _fail(where, "capability names must not be empty")


@dataclass(frozen=True)
class InitializeResult(Message):
    protocol_version: int = _json("protocolVersion", minimum=1)
    runner: Named = _json("runner")
    capabilities: list[str] = _json("capabilities", unique=True)

    def _check(self, where: str) -> None:
        if any(not name for name in self.capabilities):
            raise _fail(where, "capability names must not be empty")


# Starting, cancelling and shutting down


@dataclass(frozen=True)
class StartLimits(Message):
    event_max_bytes: int = _json("eventMaxBytes", minimum=1)


@dataclass(frozen=True)
class RunStartParams(Message):
    run_id: str = _json("runId", pattern=RUN_ID_PATTERN)
    instructions: str = _json("instructions")
    workspace: str = _json("workspace", min_length=1)
    options: dict[str, object] = _json("options")
    limits: StartLimits = _json("limits")


@dataclass(frozen=True)
class RunStartResult(Message):
    run_id: str = _json("runId", pattern=RUN_ID_PATTERN)


@dataclass(frozen=True)
class RunCancelParams(Message):
    run_id: str = _json("runId", pattern=RUN_ID_PATTERN)


@dataclass(frozen=True)
class Empty(Message):
    """The params of shutdown, and the result of run/cancel and shutdown."""


# Run events


@dataclass(frozen=True)
class Engine(Message):
    name: str = _json("name", min_length=1)
    version: str | None = _json("version", default=None, min_length=1)
    model: str | None = _json("model", default=None, min_length=1)


@dataclass(frozen=True)
class RunEvent(Message):
    """Every run event: the run id, its seq, and (as TYPE) its type."""

    run_id: str = _json("runId", pattern=RUN_ID_PATTERN)
    seq: int = _json("seq", minimum=0)


@dataclass(frozen=True)
class InitEvent(RunEvent):
    TYPE: ClassVar[str | None] = "init"
    runner: Named = _json("runner")
    tools: list[str] = _json("tools")
    engine: Engine | None = _json("engine", default=None)
    native: dict[str, object] | None = _json("native", default=None)

    def _check(self, where: str) -> None:
        if self.seq != 0:
            raise _fail(where, f"an init event's seq is always 0, not {self.seq}")
        if any(not tool for tool in self.tools):
            raise _fail(where, "tool names must not be empty")


@dataclass(frozen=True)
class TurnEvent(RunEvent):
    TYPE: ClassVar[str | None] = "turn"
    role: Literal["assistant", "user"] = _json("role")
    text: str = _json("text")
    native: dict[str, object] | None = _json("native", default=None)


@dataclass(frozen=True)
class ToolCallEvent(RunEvent):
    TYPE: ClassVar[str | None] = "tool_call"
    call_id: str = _json("callId", min_length=1)
    tool: str = _json("tool", min_length=1)
    input_summary: str = _json("inputSummary")
    native: dict[str, object] | None = _json("native", default=None)


@dataclass(frozen=True)
class ToolResultEvent(RunEvent):
    TYPE: ClassVar[str | None] = "tool_result"
    call_id: str = _json("callId", min_length=1)
    is_error: bool = _json("isError")
    output_summary: str = _json("outputSummary")
    output_bytes: int = _json("outputBytes", minimum=0)


RetryReason = Literal["authentication", "rate-limit", "network", "server", "other"]


@dataclass(frozen=True)
class RetryEvent(RunEvent):
    TYPE: ClassVar[str | None] = "retry"
    attempt: int = _json("attempt", minimum=1)
    delay_ms: int = _json("delayMs", minimum=0)
    reason: RetryReason = _json("reason")
    max_attempts: int | None = _json("maxAttempts", default=None, minimum=1)
    message: str | None = _json("message", default=None)


@dataclass(frozen=True)
class LogEvent(RunEvent):
    TYPE: ClassVar[str | None] = "log"
    level: Literal["debug", "info", "warning", "error"] = _json("level")
    message: str = _json("message")


@dataclass(frozen=True)
class ResultEvent(RunEvent):
    TYPE: ClassVar[str | None] = "result"
    status: Literal["ok", "error"] = _json("status")
    message: str = _json("message")
    turns: int | None = _json("turns", default=None, minimum=0)
    duration_ms: int | None = _json("durationMs", default=None, minimum=0)
    usage: dict[str, int] | None = _json("usage", default=None, minimum=0)
    cost_usd: float | None = _json("costUsd", default=None, minimum=0)
    native: dict[str, object] | None = _json("native", default=None)


EventType = Literal["init", "turn", "tool_call", "tool_result", "retry", "log", "result"]


@dataclass(frozen=True)
class OversizedEvent(RunEvent):
    """Written by troupe in place of an event over the maximum size; never sent by a runner."""

    TYPE: ClassVar[str | None] = "oversized"
    original_type: EventType = _json("originalType")
    bytes: int = _json("bytes", minimum=1)
    ref: str = _json("ref", pattern=REF_PATTERN)


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
        raise _fail("run event", "must be an object")
    kind = data.get("type")
    if not isinstance(kind, str) or kind not in EVENT_TYPES:
        raise _fail("run event", f"unknown event type {kind!r}")
    return EVENT_TYPES[kind].from_data(data)


@dataclass(frozen=True)
class TranscriptRecord(Message):
    run_id: str = _json("runId", pattern=RUN_ID_PATTERN)
    record: str = _json("record")
    encoding: Literal["utf-8", "base64"] | None = _json("encoding", default=None)


# Errors and JSON-RPC envelopes


@dataclass(frozen=True)
class ErrorData(Message):
    """troupe's structured error (protocol/schemas/error.schema.json) carried in an error's data."""

    code: str = _json("code", pattern=re.compile(r"\A[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+\Z"))
    problem: str = _json("problem", min_length=1)
    fix: str = _json("fix", min_length=1)
    path: str | None = _json("path", default=None, min_length=1)
    details: dict[str, object] | None = _json("details", default=None)


@dataclass(frozen=True)
class RpcError(Message):
    code: int = _json("code")
    message: str = _json("message", min_length=1)
    data: ErrorData = _json("data")


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


def parse_line(line: bytes) -> Incoming:
    """Read one line a runner wrote: a notification, a success response or an error response."""
    try:
        data = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(f"not JSON: {error}") from error
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
