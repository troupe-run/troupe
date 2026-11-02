"""Helpers for the tool tests: a workspace, a call, and a fake model that issues calls the way an
engine's tool loop would (spec: runner-tools; #240's "done when")."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from runner_schemas import validate
from troupe_plugin_sdk.effects import READ_ONLY, Effects
from troupe_plugin_sdk.events import EventNumbering
from troupe_plugin_sdk.tools import Tools, ToolStep

RUN = "0f8fad5b-d9cb-469f-a165-70867728950e"


def workspace(tmp_path: Path, files: Mapping[str, bytes] | None = None) -> Path:
    """A workspace directory holding ``files`` (workspace-relative path to bytes)."""
    root = tmp_path / "workspace"
    root.mkdir()
    for name, data in (files or {}).items():
        target = root.joinpath(*name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def call(
    tools: Tools,
    name: str,
    arguments: Mapping[str, object] | str,
    numbering: EventNumbering | None = None,
    call_id: str = "c1",
) -> ToolStep:
    """Run one call, and check both its events against the contract's schema."""
    step = tools.run(call_id, name, arguments, numbering or EventNumbering(RUN, 65536, next_seq=1))
    for event in step.events:
        validate(event.to_data(), "run-event.schema.json#/$defs/event", runner=None)
    return step


@dataclass
class FakeModel:
    """A model that answers with the tool calls it was given, one at a time, and keeps what each
    call returned, as an engine's conversation would."""

    calls: Sequence[tuple[str, Mapping[str, object] | str]]
    seen: list[tuple[str, bool]] = field(default_factory=list)

    def drive(self, tools: Tools, numbering: EventNumbering) -> list[ToolStep]:
        steps: list[ToolStep] = []
        for index, (name, arguments) in enumerate(self.calls):
            step = tools.run(f"call-{index}", name, arguments, numbering)
            self.seen.append((step.output, step.is_error))
            steps.append(step)
        return steps


def tools_for(root: Path, effects: Effects = READ_ONLY) -> Tools:
    return Tools(root, effects)


def as_text(arguments: Mapping[str, object]) -> str:
    """Arguments as Chat Completions sends them: the JSON text of an object."""
    return json.dumps(arguments)
