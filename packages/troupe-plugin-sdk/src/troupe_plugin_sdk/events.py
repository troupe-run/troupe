"""Numbering a run's events and fitting them to the run's limits (spec: runner-tools, "Run events
fit the run's limits"; runner-sdk design D11).

A runner numbers every event it sends from 0, with no gaps. ``EventNumbering`` is that counter, and
the runner uses it for its own events too, so tool events slot into the same sequence. Summaries
are cut at a UTF-8 boundary to the summary limit, then further until the whole event fits
run/start's ``eventMaxBytes``, measured as troupe's host measures it: the event's compact JSON.

``context_event`` builds the event a runner sends when content of the conversation is lost and the
run carries on (spec: plugin-sdk, "The SDK builds a context event fitted to the run's limits";
context-event design D7).
"""

import json
import typing
from typing import Any

from troupe_plugin_sdk.defaults import SUMMARY_MAX_BYTES
from troupe_plugin_sdk.messages import fail
from troupe_plugin_sdk.runner import ContextBy, ContextEvent, ContextKind


class EventNumbering:
    """A run's event counter and its size limits. ``take`` gives the next ``seq``."""

    def __init__(
        self,
        run_id: str,
        event_max_bytes: int,
        next_seq: int = 0,
        summary_max_bytes: int = SUMMARY_MAX_BYTES,
    ) -> None:
        if next_seq < 0:
            raise ValueError("next_seq starts at 0")
        if event_max_bytes < 1 or summary_max_bytes < 1:
            raise ValueError("event_max_bytes and summary_max_bytes are at least 1")
        self.run_id = run_id
        self.event_max_bytes = event_max_bytes
        self.summary_max_bytes = summary_max_bytes
        self.next_seq = next_seq

    def take(self) -> int:
        seq = self.next_seq
        self.next_seq += 1
        return seq


def utf8_size(text: str) -> int:
    return len(text.encode("utf-8"))


def cut(text: str, limit: int) -> str:
    """``text`` in at most ``limit`` UTF-8 bytes. A cut text ends on a character boundary, with a
    suffix saying how many bytes were left out; if even the suffix doesn't fit, it's as much of
    the text as fits."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    kept = max(0, limit - utf8_size(f" … [{len(data)} bytes left out]"))
    while True:
        head = data[:kept].decode("utf-8", errors="ignore")
        suffix = f" … [{len(data) - utf8_size(head)} bytes left out]"
        if utf8_size(head) + utf8_size(suffix) <= limit:
            return head + suffix
        if kept == 0:
            return data[:limit].decode("utf-8", errors="ignore")
        kept -= 1


def encoded_size(data: dict[str, Any]) -> int:
    """The bytes troupe's host counts for an event: its params as compact UTF-8 JSON."""
    return utf8_size(json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def fit(data: dict[str, Any], field: str, limit: int, event_max_bytes: int) -> dict[str, Any]:
    """``data`` with its ``field`` cut to ``limit`` bytes and, if the event still doesn't fit
    ``event_max_bytes``, cut further. An event whose other fields alone are over the limit keeps
    an empty summary; troupe's host then keeps it as an oversized event."""
    full: str = data[field]
    fitted = {**data, field: cut(full, limit)}
    while (over := encoded_size(fitted) - event_max_bytes) > 0 and fitted[field]:
        limit = max(0, utf8_size(fitted[field]) - over)
        fitted = {**data, field: cut(full, limit)}
    return fitted


_COUNTS = (
    ("tokensBefore", "tokens_before"),
    ("tokensAfter", "tokens_after"),
    ("messagesBefore", "messages_before"),
    ("messagesAfter", "messages_after"),
)


def context_event(
    numbering: EventNumbering,
    kind: ContextKind,
    by: ContextBy,
    message: str,
    *,
    tokens_before: int | None = None,
    tokens_after: int | None = None,
    messages_before: int | None = None,
    messages_after: int | None = None,
) -> ContextEvent:
    """A numbered ``context`` event: ``kind`` and ``by`` from the contract's lists, ``message``
    fitted like a summary, and each count left out when it's None. A kind or ``by`` off its list
    raises a protocol error before a ``seq`` is taken, so the counter is left as it was."""
    if kind not in typing.get_args(ContextKind):
        raise fail(
            "ContextEvent.kind", f"{kind!r} isn't one of {list(typing.get_args(ContextKind))}"
        )
    if by not in typing.get_args(ContextBy):
        raise fail("ContextEvent.by", f"{by!r} isn't one of {list(typing.get_args(ContextBy))}")
    given = {
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "messages_before": messages_before,
        "messages_after": messages_after,
    }
    data: dict[str, Any] = {
        "runId": numbering.run_id,
        "seq": numbering.next_seq,
        "type": "context",
        "kind": kind,
        "by": by,
        "message": message,
    }
    data.update({name: given[arg] for name, arg in _COUNTS if given[arg] is not None})
    event = ContextEvent.from_data(
        fit(data, "message", numbering.summary_max_bytes, numbering.event_max_bytes)
    )
    numbering.take()
    return event
