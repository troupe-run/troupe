"""Reading a streamed Responses API response into one reply (openai-style-runner design D4).

The stream is server-sent events: an ``event:`` line naming the type, a ``data:`` line holding it as
JSON (whose ``type`` says the same), and a blank line. There's no ``[DONE]``: the stream ends after
its final event. The reply is the response object the final event carries, never something built
from deltas: ``response.completed``, ``response.incomplete`` and ``response.failed`` each carry the
whole response, its output items, status and usage. An ``error`` event, which a service can send
mid-stream, is final too. Deltas only show the model working, and are read past.

A stream that ends without a final event, or holds an event that can't be read, is broken:
StreamError, and the partial response is dropped whole, tool calls it had begun included.

    parser = StreamParser()
    for line in response.lines():
        if parser.feed(line):    # true once the final event is read
            break
    reply = parser.reply()       # or StreamError
"""

import json
from dataclasses import dataclass
from typing import Any

FINAL = ("response.completed", "response.incomplete", "response.failed")
"""The events that carry the whole response and end the stream."""

ERROR = "error"
"""The event a service sends mid-stream when it fails; it ends the stream too."""


class StreamError(Exception):
    """The stream broke, or held something that isn't an event. The message says what, in words a
    person can act on."""


@dataclass(frozen=True)
class ToolCall:
    """One ``function_call`` output item."""

    call_id: str | None
    name: str
    arguments: str
    """The arguments as the model wrote them: JSON text, which may not be valid."""


@dataclass(frozen=True)
class Failure:
    """Why the service failed the response: its error code and message."""

    code: str | None
    message: str


@dataclass(frozen=True)
class Reply:
    """One response, as its final event gave it."""

    status: str
    """completed, incomplete or failed as the service said, or ``error`` for an error event."""
    output: list[dict[str, Any]]
    """The output items unchanged, to send back in the next request's input."""
    text: str
    refusal: str | None
    tool_calls: list[ToolCall]
    incomplete_reason: str | None
    failure: Failure | None
    usage: dict[str, Any] | None
    model: str | None


def _string(value: object, where: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise StreamError(f"The response's {where} is {type(value).__name__}, not text.")


def _dict(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StreamError(f"The response's {where} isn't an object.")
    return value


def _failure(error: object) -> Failure:
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
        return Failure(
            code if isinstance(code, str) and code else None,
            message if isinstance(message, str) and message else "(no message)",
        )
    return Failure(None, str(error) if error else "(no message)")


def read_response(response: dict[str, Any], status: str | None = None) -> Reply:
    """A reply from a response object. Its own status wins; ``status``, from the final event's
    name, stands in when it gives none. Raises StreamError for one that can't be read."""
    said = _string(response.get("status"), "status")
    status = said or status
    if not status:
        raise StreamError("The response has no status.")
    output = response.get("output") or []
    if not isinstance(output, list):
        raise StreamError("The response's output isn't a list.")
    texts: list[str] = []
    refusals: list[str] = []
    calls: list[ToolCall] = []
    for index, raw in enumerate(output):
        item = _dict(raw, f"output item {index}")
        kind = item.get("type")
        if kind == "message":
            content = item.get("content") or []
            if not isinstance(content, list):
                raise StreamError(f"The response's output item {index}'s content isn't a list.")
            for part in content:
                part = _dict(part, f"output item {index}'s content")
                if part.get("type") == "output_text":
                    texts.append(_string(part.get("text"), "output text") or "")
                elif part.get("type") == "refusal":
                    refusals.append(_string(part.get("refusal"), "refusal") or "")
        elif kind == "function_call":
            calls.append(
                ToolCall(
                    _string(item.get("call_id"), "call_id") or None,
                    _string(item.get("name"), "tool call's name") or "",
                    _string(item.get("arguments"), "tool call's arguments") or "",
                )
            )
    details = response.get("incomplete_details")
    reason = (
        _string(details.get("reason"), "incomplete reason") if isinstance(details, dict) else None
    )
    error = response.get("error")
    usage = response.get("usage")
    if usage is not None and not isinstance(usage, dict):
        raise StreamError("The response's usage isn't an object.")
    return Reply(
        status=status,
        output=list(output),
        text="".join(texts),
        refusal="".join(refusals) if refusals else None,
        tool_calls=calls,
        incomplete_reason=reason,
        failure=_failure(error) if error else None,
        usage=usage,
        model=_string(response.get("model"), "model") or None,
    )


class StreamParser:
    """Reads one response's stream, line by line, to its final event."""

    def __init__(self) -> None:
        self._data: list[str] = []
        self._reply: Reply | None = None

    def feed(self, line: str) -> bool:
        """Read one line. True once the final event has been read: the caller stops there.
        Raises StreamError for an event that can't be read."""
        if self._reply is not None:
            raise ValueError("the stream's final event has already been read")
        if line == "":
            return self._dispatch()
        if line.startswith(":"):
            return False
        name, _, value = line.partition(":")
        if name == "data":
            self._data.append(value.removeprefix(" "))
        # event:, id: and retry: lines: the data's own type is what's read.
        return False

    def end(self) -> None:
        """The body ended: read an event it ended without a blank line after."""
        if self._data and self._reply is None:
            self._dispatch()

    def reply(self) -> Reply:
        """The reply, once the stream has ended. Raises StreamError when it ended without a final
        event."""
        self.end()
        if self._reply is None:
            raise StreamError("The response's stream ended before the service finished it.")
        return self._reply

    def _dispatch(self) -> bool:
        if not self._data:
            return False
        data, self._data = "\n".join(self._data), []
        try:
            event = json.loads(data)
        except ValueError:
            raise StreamError(
                f"An event in the response's stream isn't JSON: {data[:200]!r}."
            ) from None
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise StreamError("An event in the response's stream has no type.")
        kind = event["type"]
        if kind in FINAL:
            response = _dict(event.get("response"), f"{kind} event's response")
            self._reply = read_response(response, kind.removeprefix("response."))
            return True
        if kind == ERROR:
            failure = _failure(event.get("error") or event)
            self._reply = Reply("error", [], "", None, [], None, failure, None, None)
            return True
        return False


__all__ = [
    "ERROR",
    "FINAL",
    "Failure",
    "Reply",
    "StreamError",
    "StreamParser",
    "ToolCall",
    "read_response",
]
