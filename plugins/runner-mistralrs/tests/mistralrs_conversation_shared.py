"""Helpers that test_mistralrs_conversation.py shares with other test modules."""

import json
from typing import Any

from mistralrs_harness import validator
from troupe_plugin_sdk import runner as p


class Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.records: list[tuple[str, Any]] = []
        self.stop = False

    def event(self, event: p.RunEvent) -> None:
        data = event.to_data()
        validator("run-event.schema.json#/$defs/event").validate(data)
        self.events.append(data)

    def transcript(self, kind: p.TranscriptKind, record: bytes) -> None:
        self.records.append((kind, json.loads(record)))

    def stopping(self) -> bool:
        return self.stop

    def of(self, type_: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == type_]

    @property
    def result(self) -> dict[str, Any]:
        (result,) = self.of("result")
        return result
