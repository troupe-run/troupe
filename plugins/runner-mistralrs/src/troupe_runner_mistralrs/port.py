"""What the runner needs of its engine, and what the engine's failures mean (in-process-runner
design D6, D7, D10).

The conversation talks to an ``Engine`` and never to ``mistralrs`` itself: ``engine.py`` is the one
real implementation, and the tests give the runner a stand-in that serves recorded responses. This
module imports nothing of ``mistralrs``, so the runner can import it before it has moved file
descriptor 1 off the protocol channel (design D3).

The engine reports every failure as a plain ``ValueError`` whose words say what happened. Those
words are mapped here, in one table, with a test per message captured from the engine, so a new
version that words them differently fails a test rather than reporting a full context as an engine
error.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

FailureKind = Literal["metal", "too-long", "other"]
"""What an engine failure means: Metal kernels that don't compile under this Python; a request
longer than the model's length or its KV budget; anything else."""

FAILURES: tuple[tuple[str, FailureKind], ...] = (
    ("Error while loading library", "metal"),
    ("Prompt sequence length is greater than", "too-long"),
    ("exceeds the total KV cache capacity", "too-long"),
)
"""The engine's own words for each failure the runner tells apart, as mistral.rs 0.9.5 words them
(probed on #414, comment 6866903650). The first match decides; no match is ``other``."""


def classify(message: str) -> FailureKind:
    """What the engine's failure ``message`` means (the table above)."""
    return next((kind for words, kind in FAILURES if words in message), "other")


class EngineFailure(Exception):  # noqa: N818 - the engine's failure, named as the engine reports it
    """The engine refused or failed: ``message`` is its own words, ``kind`` what they mean."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.kind = classify(message)


@dataclass(frozen=True)
class LoadSpec:
    """How to load the run's model."""

    model: Path
    seed: int | None = None
    kv_tokens: int | None = None
    """The KV budget, in tokens, on Metal (the run's window); None elsewhere, where CPU builds
    refuse a budget (design D7)."""


@dataclass(frozen=True)
class ToolCall:
    """One tool call in an answer, as the engine gives it: arguments are JSON text."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ChatRequest:
    """One request to the engine: what the runner passes it, nothing of the engine's own tools."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    max_tokens: int
    temperature: float | None = None
    think: bool | None = None

    def settings(self) -> dict[str, Any]:
        """Everything but the messages, as the transcript records it."""
        data: dict[str, Any] = {"max_tokens": self.max_tokens}
        if self.temperature is not None:
            data["temperature"] = self.temperature
        if self.think is not None:
            data["enable_thinking"] = self.think
        return data

    def to_data(self) -> dict[str, Any]:
        """The whole request as the transcript records it: the fields the runner sets, with the
        tools as JSON, the same fields engine.py passes the library."""
        return {
            "messages": self.messages,
            "tool_schemas": self.tools,
            "tool_choice": "auto",
            "truncate_sequence": False,
            **self.settings(),
        }


@dataclass(frozen=True)
class Answer:
    """The engine's response to one request."""

    content: str
    reasoning: str
    tool_calls: list[ToolCall]
    finish_reason: str
    prompt_tokens: int | None
    completion_tokens: int | None
    record: Mapping[str, Any] = field(default_factory=dict)
    """The response as the engine returned it, serialised, for the transcript."""


class Engine(Protocol):
    """A loaded model."""

    @property
    def version(self) -> str:
        """The engine's version, as the init event names it."""
        ...

    def max_sequence_length(self) -> int | None:
        """The model's own length, in tokens, or None when it doesn't say."""
        ...

    def count(self, text: str) -> int:
        """How many tokens ``text`` is, by the model's own tokenizer."""
        ...

    def chat(self, request: ChatRequest) -> Answer:
        """The model's answer to ``request``. Raises EngineFailure."""
        ...


Loader = Callable[[LoadSpec], Engine]
"""Loads the run's model. Raises EngineFailure."""

PlatformCheck = Callable[[], None]
"""Checks, before the run is acknowledged, that the engine can run under this Python: on macOS it
loads the check model. Raises EngineFailure."""


def tool_schema_text(tools: list[dict[str, Any]]) -> list[str]:
    """``tools`` as the engine's ``tool_schemas`` takes them: one JSON text each."""
    return [json.dumps(tool, ensure_ascii=False, separators=(",", ":")) for tool in tools]
