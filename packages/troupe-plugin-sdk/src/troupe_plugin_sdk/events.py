"""Numbering a run's events and fitting them to the run's limits (spec: runner-tools, "Run events
fit the run's limits"; runner-sdk design D11).

A runner numbers every event it sends from 0, with no gaps. ``EventNumbering`` is that counter, and
the runner uses it for its own events too, so tool events slot into the same sequence. Summaries
are cut at a UTF-8 boundary to the summary limit, then further until the whole event fits
run/start's ``eventMaxBytes``, measured as troupe's host measures it: the event's compact JSON.

``ServedModels`` decides when a runner reports the model that answered (spec: runner-protocol, "A
model other than init's is reported as it answers"; served-model design D2 to D4).
"""

import json
from typing import Any

from troupe_plugin_sdk.defaults import SUMMARY_MAX_BYTES
from troupe_plugin_sdk.runner import MODEL_PATTERN

SHOWN_MODEL_MAX_BYTES = 256
"""How much of a model name that can't be recorded a ``log`` warning shows."""


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
