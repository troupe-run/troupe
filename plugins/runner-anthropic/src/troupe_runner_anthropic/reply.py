"""One reply, gathered from its stream events (anthropic-runner design D7).

A streamed reply is ``message_start``, then for each content block ``content_block_start``, its
deltas and ``content_block_stop``, then ``message_delta`` (the stop reason and the output's usage)
and ``message_stop``. The parser takes each event as the library parsed it and builds the reply the
loop acts on. A reply is whole only at ``message_stop``: a stream that ends before it is broken, and
nothing in it is acted on.

The content goes back to the service unchanged as the next request's assistant message, so each
block keeps every field the service sent, its ``thinking`` signature included. A ``tool_use``
block's input arrives as JSON text in pieces; the parser joins them and parses the whole. Input
that doesn't parse as a JSON object is kept as text for the SDK to answer as malformed, and the
block goes back with ``input`` ``{}``, the one change, since the API takes only an object there.
"""

import json
from dataclasses import dataclass, field
from typing import Any


class ShapeError(Exception):
    """A reply the runner can't read: the service finished it in a shape it can't act on."""

    def __init__(self, message: str, usage: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.usage = usage


@dataclass(frozen=True)
class ToolUse:
    """One tool call a reply asks for."""

    call_id: str
    name: str
    arguments: dict[str, Any] | str
    """The input as an object, or its text when it isn't one, for the SDK to answer as malformed."""


@dataclass(frozen=True)
class Reply:
    """A whole reply."""

    content: list[dict[str, Any]]
    """Its content blocks, as the next request sends them back."""
    stop_reason: str | None
    stop_details: object
    model: str | None
    usage: dict[str, Any] | None
    """``input_tokens``, ``output_tokens`` and the cache counters, as the service reported them."""
    text: str
    """Its ``text`` blocks, joined."""
    tool_uses: list[ToolUse]

    @property
    def prompt_tokens(self) -> int | None:
        """The reported size of the prompt it answered: its input and both cache counters (design
        D8), or None when the service didn't report input tokens."""
        usage = self.usage or {}
        given = usage.get("input_tokens")
        if not _count(given):
            return None
        total = 0
        for value in (
            given,
            usage.get("cache_read_input_tokens"),
            usage.get("cache_creation_input_tokens"),
        ):
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                total += value
        return total


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass
class _Block:
    block: dict[str, Any]
    json_text: list[str] = field(default_factory=list)
    stopped: bool = False


@dataclass
class ReplyParser:
    """Takes a reply's events in order; ``reply()`` once ``feed`` has returned True."""

    _message: dict[str, Any] | None = None
    _blocks: dict[int, _Block] = field(default_factory=dict)
    _usage: dict[str, Any] = field(default_factory=dict)
    _stop_reason: str | None = None
    _stop_details: object = None
    _stopped: bool = False

    def feed(self, event: dict[str, Any]) -> bool:
        """Take one event; True once it was ``message_stop``. Raises ShapeError for an event the
        runner can't place."""
        kind = event.get("type")
        if kind == "message_start":
            message = event.get("message")
            if not isinstance(message, dict):
                raise ShapeError("its message_start event holds no message")
            self._message = message
            usage = message.get("usage")
            if isinstance(usage, dict):
                self._usage.update({k: v for k, v in usage.items() if v is not None})
            return False
        if self._message is None:
            raise ShapeError(f"its first event is {kind!r}, not message_start")
        if kind == "content_block_start":
            index, block = event.get("index"), event.get("content_block")
            if not isinstance(index, int) or not isinstance(block, dict):
                raise ShapeError("a content_block_start event holds no index or block")
            self._blocks[index] = _Block(dict(block))
        elif kind == "content_block_delta":
            self._delta(event)
        elif kind == "content_block_stop":
            started = self._started(event)
            started.stopped = True
        elif kind == "message_delta":
            delta = event.get("delta")
            if isinstance(delta, dict):
                if "stop_reason" in delta:
                    reason = delta.get("stop_reason")
                    self._stop_reason = reason if isinstance(reason, str) else None
                if delta.get("stop_details") is not None:
                    self._stop_details = delta.get("stop_details")
            usage = event.get("usage")
            if isinstance(usage, dict):
                self._usage.update({k: v for k, v in usage.items() if v is not None})
        elif kind == "message_stop":
            self._stopped = True
            return True
        # Any other event (a ping, one a later API adds) changes nothing the runner reads.
        return False

    def _started(self, event: dict[str, Any]) -> _Block:
        index = event.get("index")
        started = self._blocks.get(index) if isinstance(index, int) else None
        if started is None:
            raise ShapeError(f"a {event.get('type')} event names a content block it never started")
        return started

    def _delta(self, event: dict[str, Any]) -> None:
        started = self._started(event)
        delta = event.get("delta")
        if not isinstance(delta, dict):
            raise ShapeError("a content_block_delta event holds no delta")
        block = started.block
        kind = delta.get("type")
        if kind == "text_delta":
            block["text"] = str(block.get("text", "")) + str(delta.get("text", ""))
        elif kind == "input_json_delta":
            started.json_text.append(str(delta.get("partial_json", "")))
        elif kind == "thinking_delta":
            block["thinking"] = str(block.get("thinking", "")) + str(delta.get("thinking", ""))
        elif kind == "signature_delta":
            block["signature"] = str(block.get("signature", "")) + str(delta.get("signature", ""))
        elif kind == "citations_delta":
            citations = block.setdefault("citations", [])
            if isinstance(citations, list):
                citations.append(delta.get("citation"))

    def reply(self) -> Reply:
        """The whole reply. Raises ShapeError for one the runner can't act on."""
        assert self._message is not None  # noqa: S101 - feed returned True
        assert self._stopped  # noqa: S101
        usage = dict(self._usage) if self._usage else None
        content: list[dict[str, Any]] = []
        tool_uses: list[ToolUse] = []
        texts: list[str] = []
        for index in sorted(self._blocks):
            started = self._blocks[index]
            block = started.block
            if block.get("type") == "tool_use":
                call_id, name = block.get("id"), block.get("name")
                if not isinstance(call_id, str) or not call_id:
                    raise ShapeError(f"a tool_use block ({name!r}) has no id", usage)
                if not isinstance(name, str) or not name:
                    raise ShapeError(f"the tool_use block {call_id} has no name", usage)
                arguments = _arguments(started)
                block["input"] = arguments if isinstance(arguments, dict) else {}
                tool_uses.append(ToolUse(call_id, name, arguments))
            elif block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
            content.append(block)
        model = self._message.get("model")
        return Reply(
            content=content,
            stop_reason=self._stop_reason,
            stop_details=self._stop_details,
            model=model if isinstance(model, str) and model else None,
            usage=usage,
            text="\n\n".join(texts),
            tool_uses=tool_uses,
        )


def _arguments(started: _Block) -> dict[str, Any] | str:
    """A tool_use block's input: the joined JSON text parsed, or the input the block started with
    when no text came, or the text itself when it isn't a JSON object."""
    text = "".join(started.json_text)
    if not text.strip():
        given = started.block.get("input")
        return given if isinstance(given, dict) else {}
    try:
        value = json.loads(text)
    except ValueError:
        return text
    return value if isinstance(value, dict) else text


__all__ = ["Reply", "ReplyParser", "ShapeError", "ToolUse"]
