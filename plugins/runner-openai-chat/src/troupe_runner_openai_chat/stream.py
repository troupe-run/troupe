"""Reading a streamed Chat Completions response into one reply (openai-style-runner design D4).

The response is server-sent events: ``data:`` lines, each event ended by a blank line, and
``data: [DONE]`` at the end. Each event's data is a ``chat.completion.chunk``. The reply is built
from choice 0's deltas: its text, a refusal, reasoning (kept only for the transcript), and tool
calls accumulated by ``index`` (the first delta of each gives its id and name, later ones append to
its arguments). Usage comes from whichever chunk carries it, normally the last, whose choices are
empty.

A reply is complete only when a finish reason has arrived and the stream has ended. Anything else,
or an event that isn't a chunk, is a broken stream: StreamError, and the reply is dropped whole,
tool calls it had begun included.

    parser = StreamParser()
    for line in response.lines():
        if parser.feed(line):    # true at data: [DONE]
            break
    reply = parser.reply()       # or StreamError
"""

import json
from dataclasses import dataclass, field
from typing import Any

DONE = "[DONE]"


class StreamError(Exception):
    """The stream broke, or held something that isn't a chunk. The message says what, in words a
    person can act on."""


@dataclass
class ToolCall:
    """One tool call the model asked for."""

    index: int
    id: str | None
    name: str
    arguments: str
    """The arguments as the model wrote them: JSON text, which may not be valid."""


@dataclass
class Reply:
    """One complete response."""

    text: str
    refusal: str | None
    reasoning: str
    tool_calls: list[ToolCall]
    finish: str
    usage: dict[str, Any] | None
    """The service's usage record as it sent it, or None when it sent none."""
    model: str | None
    """The model the service says answered, or None when it didn't say."""


@dataclass
class _Building:
    text: list[str] = field(default_factory=list)
    refusal: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    calls: dict[int, ToolCall] = field(default_factory=dict)
    finish: str | None = None
    usage: dict[str, Any] | None = None
    model: str | None = None


def _string(value: object, where: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise StreamError(f"The stream's {where} is {type(value).__name__}, not text.")


class StreamParser:
    """Builds one Reply from a response's lines, fed in order."""

    def __init__(self) -> None:
        self._building = _Building()
        self._data: list[str] = []
        self._done = False

    def feed(self, line: str) -> bool:
        """Read one line. Returns True once ``data: [DONE]`` has been read; feeding more after it
        is a mistake of the caller's. Raises StreamError for an event that isn't a chunk."""
        if self._done:
            raise ValueError("the stream has already ended")
        if line == "":
            return self._dispatch()
        if line.startswith(":"):
            return False
        name, _, value = line.partition(":")
        if name != "data":
            return False  # event, id and retry fields: Chat Completions doesn't use them
        self._data.append(value.removeprefix(" "))
        return False

    def end(self) -> None:
        """The body ended: read any event it ended without a blank line after."""
        if self._data and not self._done:
            self._dispatch()

    def reply(self) -> Reply:
        """The reply, once the stream has ended. Raises StreamError when it ended before a finish
        reason."""
        self.end()
        building = self._building
        if building.finish is None:
            raise StreamError("The response's stream ended before the model finished its reply.")
        calls = [building.calls[index] for index in sorted(building.calls)]
        return Reply(
            text="".join(building.text),
            refusal="".join(building.refusal) if building.refusal else None,
            reasoning="".join(building.reasoning),
            tool_calls=calls,
            finish=building.finish,
            usage=building.usage,
            model=building.model,
        )

    def _dispatch(self) -> bool:
        if not self._data:
            return False
        data, self._data = "\n".join(self._data), []
        if data == DONE:
            self._done = True
            return True
        try:
            chunk = json.loads(data)
        except ValueError:
            raise StreamError(
                f"An event in the response's stream isn't JSON: {data[:200]!r}."
            ) from None
        if not isinstance(chunk, dict):
            raise StreamError("An event in the response's stream isn't a JSON object.")
        self._chunk(chunk)
        return False

    def _chunk(self, chunk: dict[str, Any]) -> None:
        building = self._building
        if "error" in chunk:
            error = chunk["error"]
            message = error.get("message") if isinstance(error, dict) else error
            raise StreamError(f"The service reported an error mid-stream: {message}.")
        model = _string(chunk.get("model"), "model")
        if model:
            building.model = model
        usage = chunk.get("usage")
        if usage is not None:
            if not isinstance(usage, dict):
                raise StreamError("The stream's usage isn't an object.")
            building.usage = usage
        choices = chunk.get("choices", [])
        if not isinstance(choices, list):
            raise StreamError("The stream's choices aren't a list.")
        for choice in choices:
            if not isinstance(choice, dict):
                raise StreamError("A choice in the stream isn't an object.")
            if choice.get("index", 0) != 0:
                continue
            self._choice(choice)

    def _choice(self, choice: dict[str, Any]) -> None:
        building = self._building
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            raise StreamError("A delta in the stream isn't an object.")
        for key, parts in (("content", building.text), ("refusal", building.refusal)):
            value = _string(delta.get(key), key)
            if value:
                parts.append(value)
        for key in ("reasoning_content", "reasoning"):
            value = _string(delta.get(key), key)
            if value:
                building.reasoning.append(value)
        calls = delta.get("tool_calls") or []
        if not isinstance(calls, list):
            raise StreamError("The stream's tool_calls aren't a list.")
        for call in calls:
            self._call(call)
        finish = _string(choice.get("finish_reason"), "finish_reason")
        if finish:
            building.finish = finish

    def _call(self, call: object) -> None:
        calls = self._building.calls
        if not isinstance(call, dict):
            raise StreamError("A tool call in the stream isn't an object.")
        index = call.get("index", len(calls))
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise StreamError(f"A tool call's index in the stream is {index!r}.")
        function = call.get("function") or {}
        if not isinstance(function, dict):
            raise StreamError("A tool call's function in the stream isn't an object.")
        call_id = _string(call.get("id"), "tool call id")
        name = _string(function.get("name"), "tool call name")
        arguments = _string(function.get("arguments"), "tool call arguments")
        if index not in calls:
            calls[index] = ToolCall(index, call_id or None, name or "", arguments or "")
            return
        existing = calls[index]
        if call_id and not existing.id:
            existing.id = call_id
        if name and not existing.name:
            existing.name = name
        existing.arguments += arguments or ""


__all__ = ["DONE", "Reply", "StreamError", "StreamParser", "ToolCall"]
