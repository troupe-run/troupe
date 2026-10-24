"""Claude Code's stream-json, mapped onto run events one line at a time (design D5).

The mapper is pure: a line of Claude Code's standard output goes in, and the transcript record and
run events it maps to come out, with no I/O. The runner and the fixture tests use the same mapper,
so the mapping the tests check is the mapping the runner runs. Events come out without ``runId``
and ``seq``: the runner numbers them as it sends them.

The mapping is contributing/runners.md's "Mapping an engine: Claude Code" table, plus what the
table leaves open: retries with no HTTP status, permission denials, records it doesn't name,
lines that aren't JSON, and summaries cut to fit the event limit.
"""

import base64
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, TypeGuard

from troupe_runner_claude_code import NAME
from troupe_runner_claude_code.defaults import SUMMARY_MAX_BYTES

ENGINE = "claude-code"
"""The engine's name in the init event."""

USAGE = {
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cache_read_input_tokens": "cacheReadTokens",
    "cache_creation_input_tokens": "cacheWriteTokens",
}
"""Claude Code's usage counters, by the names the result event gives them."""

SUMMARY_FIELDS = {
    "turn": "text",
    "tool_call": "inputSummary",
    "tool_result": "outputSummary",
    "retry": "message",
    "log": "message",
    "result": "message",
}
"""The one free-text field of each event type that may be cut to fit. An init has none: its tool
list can't be cut, and troupe stores an init too large to keep inline as an oversized event."""

_SIZING_RUN_ID = "00000000-0000-4000-8000-000000000000"
_SIZING_SEQ = 10**15
"""Stand-ins for the runId and seq the runner adds, at least as long as any real ones, so an
event that fits here fits when it is sent."""


@dataclass(frozen=True)
class Transcript:
    """One native line as a run/transcript record."""

    record: str
    encoding: str | None = None
    """None for UTF-8 text (the contract's default), or "base64"."""


@dataclass(frozen=True)
class Event:
    """One run event, without runId and seq."""

    event: dict[str, Any]


Out = Transcript | Event


class NotJsonError(ValueError):
    """A line or message that isn't strict JSON."""


def _refuse_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NotJsonError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _refuse_constant(name: str) -> object:
    raise NotJsonError(f"{name} isn't JSON")


def loads_strict(text: str) -> object:
    """``text`` as JSON, refusing duplicate keys, NaN and Infinity, as troupe's host does."""
    try:
        return json.loads(
            text, object_pairs_hook=_refuse_duplicates, parse_constant=_refuse_constant
        )
    except (json.JSONDecodeError, RecursionError) as error:
        raise NotJsonError(str(error)) from error


def _utf8_size(text: str) -> int:
    return len(text.encode("utf-8"))


def cut(text: str, limit: int) -> str:
    """``text`` in at most ``limit`` UTF-8 bytes. A cut text ends on a character boundary, with
    a suffix saying how many bytes were left out."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    kept = max(0, limit - len(f" … [{len(data)} bytes left out]".encode()))
    while True:
        head = data[:kept].decode("utf-8", errors="ignore")
        suffix = f" … [{len(data) - _utf8_size(head)} bytes left out]"
        if _utf8_size(head) + _utf8_size(suffix) <= limit or kept == 0:
            return head + suffix
        kept -= 1


def event_size(event: dict[str, Any]) -> int:
    """The bytes troupe's host counts for ``event`` once the runner has numbered it."""
    sized = {"runId": _SIZING_RUN_ID, "seq": _SIZING_SEQ, **event}
    return len(json.dumps(sized, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _is_count(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


class Mapper:
    """Maps one run's lines. Feed it every line Claude Code writes, in order."""

    def __init__(
        self,
        runner_version: str,
        event_max_bytes: int,
        summary_max_bytes: int = SUMMARY_MAX_BYTES,
    ) -> None:
        self._runner_version = runner_version
        self._event_max_bytes = event_max_bytes
        self._summary_max_bytes = summary_max_bytes
        self._init_sent = False
        self._held: list[dict[str, Any]] = []
        """Logs about records before the init record, sent once init is."""
        self._calls: set[str] = set()
        self._noted: set[str] = set()
        self._result_sent = False
        self._silenced = False

    @property
    def init_sent(self) -> bool:
        return self._init_sent

    @property
    def result_sent(self) -> bool:
        return self._result_sent

    def silence(self) -> None:
        """Send no more events, only transcript records: the run was cancelled."""
        self._silenced = True

    def feed(self, line: bytes) -> list[Out]:
        """The transcript record and events for one line of Claude Code's standard output,
        without its line ending."""
        out: list[Out] = [_transcript(line)]
        if self._silenced or self._result_sent:
            return out
        try:
            text = line.decode("utf-8")
            record = loads_strict(text)
        except (UnicodeDecodeError, NotJsonError):
            record = None
        if not isinstance(record, dict):
            events = [_log("warning", "Claude Code wrote a line that isn't a JSON object")]
        else:
            events = self._map(record)
        return out + self._order(events)

    def finish(self, exit_status: int | None) -> list[Out]:
        """The events for Claude Code having ended with ``exit_status`` (None if unknown).

        A run that ended before Claude Code's init gets a synthetic init and a log naming the exit
        code, so the person can see why it went nowhere. Otherwise nothing: a missing result is
        troupe's to derive, and the runner never invents one.
        """
        if self._silenced or self._init_sent:
            return []
        how = "exit code unknown" if exit_status is None else f"exit code {exit_status}"
        return self._end_before_init(
            f"Claude Code ended ({how}) before it reported its init record"
        )

    def cannot_start(self, problem: str) -> list[Out]:
        """The events for Claude Code failing to start: a synthetic init and a log saying why."""
        return self._end_before_init(problem)

    def _end_before_init(self, problem: str) -> list[Out]:
        self._init_sent = True
        held, self._held = self._held, []
        ended = _log("error", problem)
        return [Event(self._synthetic_init()), *(self._fit(event) for event in [*held, ended])]

    # Ordering init

    def _order(self, events: list[dict[str, Any]]) -> list[Out]:
        """``events`` with init first: logs before init are held for it, and any other event
        before init sends a synthetic one."""
        out: list[Out] = []
        for event in events:
            if event["type"] == "init":
                if self._init_sent:
                    engine = event.get("engine", {})
                    out.append(
                        self._fit(
                            _log(
                                "info",
                                "Claude Code reported its init record late: version "
                                f"{engine.get('version', 'unknown')}, model "
                                f"{engine.get('model', 'unknown')}",
                            )
                        )
                    )
                    continue
                self._init_sent = True
                out.append(self._fit(event))
                out.extend(self._fit(held) for held in self._held)
                self._held = []
            elif not self._init_sent and event["type"] == "log":
                self._held.append(event)
            else:
                if not self._init_sent:
                    self._init_sent = True
                    out.append(Event(self._synthetic_init()))
                    out.extend(self._fit(held) for held in self._held)
                    self._held = []
                out.append(self._fit(event))
                if event["type"] == "result":
                    self._result_sent = True
        return out

    def _synthetic_init(self) -> dict[str, Any]:
        return {
            "type": "init",
            "runner": {"name": NAME, "version": self._runner_version},
            "tools": [],
        }

    # Summaries

    def _fit(self, event: dict[str, Any]) -> Event:
        """``event`` with its summary field cut to the summary limit and, if it still doesn't
        fit, to the event limit."""
        field = SUMMARY_FIELDS.get(event["type"])
        if field is None or not isinstance(event.get(field), str):
            return Event(event)
        full = event[field]
        limit = self._summary_max_bytes
        fitted = {**event, field: cut(full, limit)}
        while (over := event_size(fitted) - self._event_max_bytes) > 0 and limit > 0:
            limit = max(0, min(limit, _utf8_size(fitted[field])) - over)
            fitted = {**event, field: cut(full, limit)}
        return Event(fitted)

    # The mapping

    def _note(self, kind: str) -> list[dict[str, Any]]:
        if kind in self._noted:
            return []
        self._noted.add(kind)
        return [_log("debug", f"Claude Code record type {kind} isn't mapped")]

    def _map(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        kind = record.get("type")
        if kind == "system":
            subtype = record.get("subtype")
            if subtype == "init":
                return self._init(record)
            if subtype == "api_retry":
                return self._retry(record)
            return self._note(f"system/{subtype}")
        if kind == "assistant":
            return self._assistant(record)
        if kind == "user":
            return self._user(record)
        if kind == "rate_limit_event":
            return self._rate_limit(record)
        if kind == "result":
            return self._result(record)
        return self._note(str(kind))

    def _init(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        tools = record.get("tools", [])
        if not isinstance(tools, list) or not all(isinstance(t, str) and t for t in tools):
            return [_missing("system/init", "tools")]
        engine: dict[str, Any] = {"name": ENGINE}
        for theirs, ours in (("claude_code_version", "version"), ("model", "model")):
            if isinstance(record.get(theirs), str) and record[theirs]:
                engine[ours] = record[theirs]
        return [
            {
                "type": "init",
                "runner": {"name": NAME, "version": self._runner_version},
                "engine": engine,
                "tools": list(tools),
            }
        ]

    def _retry(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        attempt, delay = record.get("attempt"), record.get("retry_delay_ms")
        if not (_is_count(attempt) and attempt >= 1) or not _is_count(delay):
            return [_missing("system/api_retry", "attempt or retry_delay_ms")]
        error = record.get("error")
        status = record.get("error_status")
        error_text = error if isinstance(error, str) and error else "unknown"
        if error == "authentication_failed":
            reason = "authentication"
        elif status == 429:
            reason = "rate-limit"
        elif _is_count(status) and 500 <= status <= 599:
            reason = "server"
        elif status is None:
            reason = "network"
        else:
            reason = "other"
        how = "no HTTP response" if status is None else f"HTTP {status}"
        event: dict[str, Any] = {"type": "retry", "attempt": attempt}
        maximum = record.get("max_retries")
        if _is_count(maximum) and maximum >= 1:
            event["maxAttempts"] = maximum
        event.update({"delayMs": delay, "reason": reason, "message": f"{error_text} ({how})"})
        return [event]

    def _assistant(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            return [_missing("assistant", "message.content")]
        events: list[dict[str, Any]] = []
        texts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        text = "\n".join(texts)
        if text:
            events.append({"type": "turn", "role": "assistant", "text": text})
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            call_id, tool = block.get("id"), block.get("name")
            if not (isinstance(call_id, str) and call_id and isinstance(tool, str) and tool):
                events.append(_missing("assistant tool_use", "id or name"))
                continue
            self._calls.add(call_id)
            events.append(
                {
                    "type": "tool_call",
                    "callId": call_id,
                    "tool": tool,
                    "inputSummary": _compact(block.get("input", {})),
                }
            )
        return events

    def _user(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            return []
        if not isinstance(content, list):
            return [_missing("user", "message.content")]
        events: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            call_id = block.get("tool_use_id")
            if not isinstance(call_id, str) or call_id not in self._calls:
                events.append(
                    _log(
                        "warning",
                        f"Claude Code reported a result for tool call {call_id!r}, which it never "
                        "reported calling",
                    )
                )
                continue
            text, size = _tool_output(block.get("content", ""))
            is_error = block.get("is_error", False)
            events.append(
                {
                    "type": "tool_result",
                    "callId": call_id,
                    "isError": is_error is True,
                    "outputSummary": text,
                    "outputBytes": size,
                }
            )
        return events

    def _rate_limit(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        info = record.get("rate_limit_info")
        status = info.get("status") if isinstance(info, dict) else None
        if not isinstance(status, str):
            return [_missing("rate_limit_event", "rate_limit_info.status")]
        if status == "allowed":
            return []
        kind = info.get("rateLimitType") if isinstance(info, dict) else None
        return [
            _log("warning", f"rate limit {status} ({kind if isinstance(kind, str) else 'unknown'})")
        ]

    def _result(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        is_error, subtype = record.get("is_error"), record.get("subtype")
        if not isinstance(is_error, bool) or not isinstance(subtype, str):
            return [
                _log(
                    "error",
                    "Claude Code's result record has no boolean is_error and string subtype, so "
                    "the runner can't say how the run ended",
                )
            ]
        events: list[dict[str, Any]] = []
        denials = record.get("permission_denials")
        if isinstance(denials, list):
            counts = Counter(
                str(denial.get("tool_name"))
                for denial in denials
                if isinstance(denial, dict) and isinstance(denial.get("tool_name"), str)
            )
            events.extend(
                _log("warning", f"permissions denied {tool}" + (f" ({n} times)" if n > 1 else ""))
                for tool, n in counts.items()
            )
        text = record.get("result")
        event: dict[str, Any] = {
            "type": "result",
            "status": "error" if is_error or subtype != "success" else "ok",
            "message": text if isinstance(text, str) and text else subtype,
        }
        if _is_count(record.get("num_turns")):
            event["turns"] = record["num_turns"]
        if _is_count(record.get("duration_ms")):
            event["durationMs"] = record["duration_ms"]
        usage = record.get("usage")
        if isinstance(usage, dict):
            counters = {
                ours: usage[theirs]
                for theirs, ours in USAGE.items()
                if _is_count(usage.get(theirs))
            }
            if counters:
                event["usage"] = counters
        cost = record.get("total_cost_usd")
        if _is_number(cost) and cost >= 0:
            event["costUsd"] = cost
        events.append(event)
        return events


def _transcript(line: bytes) -> Transcript:
    try:
        return Transcript(line.decode("utf-8"))
    except UnicodeDecodeError:
        return Transcript(base64.b64encode(line).decode("ascii"), "base64")


def _log(level: str, message: str) -> dict[str, Any]:
    return {"type": "log", "level": level, "message": message}


def _missing(kind: str, field: str) -> dict[str, Any]:
    return _log("error", f"Claude Code's {kind} record has no usable {field}, so it isn't mapped")


def _tool_output(content: object) -> tuple[str, int]:
    """A tool result's text and its size in UTF-8 bytes. A list's text blocks are joined with
    newlines, and each other block counts as its compact JSON's bytes."""
    if isinstance(content, str):
        return content, _utf8_size(content)
    if not isinstance(content, list):
        text = _compact(content)
        return text, _utf8_size(text)
    texts: list[str] = []
    size = 0
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ):
            texts.append(block["text"])
            size += _utf8_size(block["text"])
        else:
            size += _utf8_size(_compact(block))
    text = "\n".join(texts)
    return text, size + max(0, len(texts) - 1)


__all__ = [
    "Event",
    "Mapper",
    "NotJsonError",
    "Out",
    "Transcript",
    "cut",
    "event_size",
    "loads_strict",
]
