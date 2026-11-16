"""Numbering a run's events and fitting them to the run's limits (spec: runner-tools, "Run events
fit the run's limits"; runner-sdk design D11).

A runner numbers every event it sends from 0, with no gaps. ``EventNumbering`` is that counter, and
the runner uses it for its own events too, so tool events slot into the same sequence. Summaries
are cut at a UTF-8 boundary to the summary limit, then further until the whole event fits
run/start's ``eventMaxBytes``, measured as troupe's host measures it: the event's compact JSON.

``ServedModels`` decides when a runner reports the model that answered (spec: runner-protocol, "A
model other than init's is reported as it answers"; served-model design D2 to D4).

``context_event`` builds the event a runner sends when content of the conversation is lost and the
run carries on (spec: plugin-sdk, "The SDK builds a context event fitted to the run's limits";
context-event design D7).
"""

import json
import typing
from collections.abc import Callable
from typing import Any

from troupe_plugin_sdk.defaults import SUMMARY_MAX_BYTES
from troupe_plugin_sdk.messages import fail
from troupe_plugin_sdk.runner import (
    MODEL_PATTERN,
    ContextBy,
    ContextEvent,
    ContextKind,
    surrogate_paths,
    unicode_text_counted,
)

SHOWN_MODEL_MAX_BYTES = 256
"""How much of a model name that can't be recorded a ``log`` warning shows."""


class EventNumbering:
    """A run's event counter and its size limits. ``take`` gives the next ``seq``; ``numbered``
    numbers an event body, after recording any text in it that wasn't Unicode (host-robustness
    design D3b)."""

    def __init__(
        self,
        run_id: str,
        event_max_bytes: int,
        next_seq: int = 0,
        summary_max_bytes: int = SUMMARY_MAX_BYTES,
        *,
        send_context: Callable[[ContextEvent], None],
    ) -> None:
        """``send_context`` sends a ``context`` event the moment it's numbered, ahead of the event
        whose numbering made it: it's how a replaced lone surrogate is recorded. It's required,
        so a runner can't leave a replacement unrecorded (owner, 2026-11-17)."""
        if next_seq < 0:
            raise ValueError("next_seq starts at 0")
        if event_max_bytes < 1 or summary_max_bytes < 1:
            raise ValueError("event_max_bytes and summary_max_bytes are at least 1")
        self.run_id = run_id
        self.event_max_bytes = event_max_bytes
        self.summary_max_bytes = summary_max_bytes
        self.next_seq = next_seq
        self.send_context = send_context
        self._lost: list[tuple[str, int]] = []

    def take(self) -> int:
        seq = self.next_seq
        self.next_seq += 1
        return seq

    def lost(self, where: str, replaced: int) -> None:
        """Record that ``replaced`` lone surrogates in the engine's text ``where`` (such as
        "Ollama's answer") were replaced with U+FFFD. The ``context`` event saying so is sent
        before the next event ``numbered`` numbers, or after ``init`` when that's next."""
        if not replaced:
            return
        # One context event per place: a streamed answer reports each delta (review of #437).
        for index, (waiting, count) in enumerate(self._lost):
            if waiting == where:
                self._lost[index] = (where, count + replaced)
                return
        self._lost.append((where, replaced))

    def numbered(self, body: dict[str, Any]) -> dict[str, Any]:
        """``body`` (an event without ``runId`` or ``seq``) numbered, its strings made Unicode
        text. Each replacement waiting, and any in ``body``, is first sent as a ``context`` event
        of kind ``other`` by ``runner`` naming where and how many, each with the next ``seq``, so
        the event follows them with no gap. Not before ``init``, which a ``context`` event can't
        precede: those wait for the event after it. The caller sends the event it gets back
        before numbering another."""
        clean, replaced = unicode_text_counted(body)
        if replaced:
            fields = ", ".join(surrogate_paths(body))
            self.lost(f"the {body.get('type')} event's {fields}", replaced)
        if body.get("type") != "init" and self.next_seq > 0:
            self._send_lost()
        return {"runId": self.run_id, "seq": self.take(), **clean}

    def _send_lost(self) -> None:
        while self._lost:
            where, replaced = self._lost.pop(0)
            many = replaced != 1
            message = (
                f"The engine's text wasn't Unicode: {replaced} lone surrogate{'s' if many else ''} "
                f"in {where} {'were' if many else 'was'} replaced with U+FFFD."
            )
            self.send_context(context_event(self, "other", "runner", message))


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


class ServedModels:
    """The models that answered a run, against the one its init named (None when init named
    none). ``note`` takes each name an engine or service gives and returns the event bodies to
    send for it, without ``runId`` or ``seq``, which the runner adds as it numbers its events:

    - none for an empty name, init's model, or a model already noted;
    - one ``served_model`` the first time another model answers;
    - one ``log`` warning, once per name, when the name isn't a model's shape (1 to 256
      characters, no control character), since a cut name would record a model that doesn't
      exist.
    """

    def __init__(self, asked: str | None) -> None:
        self.asked = asked
        self._noted: set[str] = set()

    def note(self, model: str | None) -> list[dict[str, Any]]:
        if not model or model == self.asked or model in self._noted:
            return []
        self._noted.add(model)
        if MODEL_PATTERN.match(model):
            return [{"type": "served_model", "model": model}]
        shown = cut(json.dumps(model, ensure_ascii=False), SHOWN_MODEL_MAX_BYTES)
        return [
            {
                "type": "log",
                "level": "warning",
                "message": f"The engine named a model troupe can't record, since it isn't 1 to "
                f"256 characters without a control character: {shown}.",
            }
        ]


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
