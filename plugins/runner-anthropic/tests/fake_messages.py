"""A fake Messages API service for the Anthropic runner's tests (anthropic-runner design D14),
adapted from the OpenAI runner's fake endpoint.

It listens on 127.0.0.1, answers each request with the next reply from its script, and records
every request it got, headers included, so a test can check what the runner sent. A reply is a
status, headers and a body, or a stream of server-sent event lines that can pause, stop short, wait
at a gate the test opens, or be held open until the client goes away.

    with FakeEndpoint([text_reply("Done."), Reply(500)]) as fake:
        fake.endpoint      # http://127.0.0.1:<port>, below which requests go to /v1/messages
        fake.requests      # each Request: method, path, headers, body

Self-contained: the standard library only.
"""

import json
import selectors
import socket
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass(frozen=True)
class Pause:
    """Wait this long before the next line of a stream."""

    seconds: float


@dataclass(frozen=True)
class Cut:
    """End the connection here, mid-stream, without the rest of the stream."""


@dataclass(frozen=True)
class Hold:
    """Keep the connection open, sending nothing, until the client closes it or the fake stops."""


@dataclass(frozen=True)
class Gate:
    """Send nothing more until ``opened`` is set, then the rest of the stream; or end the
    connection if the fake stops first. A test opens it once it has done what must happen while
    the request is in flight (request-keeps-notifications design D2)."""

    opened: threading.Event


GATE_POLL_SECONDS = 0.01
"""How often a closed gate looks whether the fake is stopping."""

StreamItem = str | Pause | Cut | Hold | Gate


@dataclass(frozen=True)
class Reply:
    """One response: a status, headers, and a body or a stream of lines (each sent with "\\n")."""

    status: int = 200
    headers: Sequence[tuple[str, str]] = ()
    body: bytes | None = None
    lines: Sequence[StreamItem] | None = None
    chunks: Sequence[bytes] | None = None
    """A streamed body as raw bytes, each piece written and flushed on its own, so a line can
    arrive split across reads anywhere."""
    no_content_type: bool = False
    """Send no Content-Type at all. Otherwise one in ``headers`` is sent, or the default: a stream
    as text/event-stream, a body as application/json."""


@dataclass(frozen=True)
class Request:
    """A request the fake got."""

    method: str
    path: str
    headers: dict[str, str]
    """By lower-case name."""
    body: bytes

    def json(self) -> Any:  # noqa: ANN401 - a request body is any JSON
        return json.loads(self.body)


@dataclass
class _State:
    script: list[Reply]
    requests: list[Request] = field(default_factory=list)
    closed_by_client: threading.Event = field(default_factory=threading.Event)
    stopping: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    arrived: threading.Condition = field(init=False)
    """Notified, under ``lock``, as each request is recorded."""

    def __post_init__(self) -> None:
        self.arrived = threading.Condition(self.lock)


def pause(seconds: float) -> None:
    """Wait until ``seconds`` have passed on time.monotonic, the clock the tests measure with. A
    bare sleep can end up to one of its ticks early by that clock: about 15.6 ms on Windows with
    Python 3.12 (#352)."""
    deadline = time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        time.sleep(left)


def _client_gone(connection: socket.socket) -> bool:
    # Not select.select: it refuses a descriptor of 1024 or more, which a long-lived test worker
    # can hand the fake, and the handler then dies without seeing the close (#301).
    with selectors.DefaultSelector() as selector:
        selector.register(connection, selectors.EVENT_READ)
        if not selector.select(0):
            return False
    try:
        return connection.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: _State

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _record(self) -> Reply:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        headers = {name.lower(): value for name, value in self.headers.items()}
        with self.state.lock:
            self.state.requests.append(Request(self.command, self.path, headers, body))
            self.state.arrived.notify_all()
            if not self.state.script:
                return Reply(500, body=b'{"error": {"message": "the fake has no reply left"}}')
            return self.state.script.pop(0)

    def do_POST(self) -> None:
        self._answer(self._record())

    def do_GET(self) -> None:
        self._answer(self._record())

    def _answer(self, reply: Reply) -> None:
        self.send_response(reply.status)
        for name, value in reply.headers:
            self.send_header(name, value)
        streamed = reply.chunks is not None or reply.lines is not None
        if not reply.no_content_type and not any(
            name.lower() == "content-type" for name, _ in reply.headers
        ):
            self.send_header(
                "Content-Type", "text/event-stream" if streamed else "application/json"
            )
        if reply.chunks is not None:
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            for piece in reply.chunks:
                self.wfile.write(piece)
                self.wfile.flush()
                time.sleep(0.001)
            return
        if reply.lines is None:
            body = reply.body or b""
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        for item in reply.lines:
            if isinstance(item, Pause):
                pause(item.seconds)
            elif isinstance(item, Cut):
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            elif isinstance(item, Gate):
                self.wfile.flush()
                while not item.opened.wait(GATE_POLL_SECONDS):
                    if self.state.stopping.is_set():
                        return
            elif isinstance(item, Hold):
                self.wfile.flush()
                while not self.state.stopping.is_set():
                    if _client_gone(self.connection):
                        self.state.closed_by_client.set()
                        return
                    time.sleep(0.01)
                return
            else:
                try:
                    self.wfile.write(item.encode("utf-8") + b"\n")
                    self.wfile.flush()
                except OSError:
                    self.state.closed_by_client.set()
                    return


class FakeEndpoint:
    """A fake Messages API service, answering from ``script`` in order."""

    def __init__(self, script: Iterable[Reply] = ()) -> None:
        self._state = _State(list(script))
        handler = type("Handler", (_Handler,), {"state": self._state})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, args=(0.02,), daemon=True
        )

    @property
    def endpoint(self) -> str:
        """The base URL a runtime names: the library sends requests to its /v1/messages."""
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}"

    @property
    def requests(self) -> list[Request]:
        with self._state.lock:
            return list(self._state.requests)

    def add(self, *replies: Reply) -> None:
        """Add replies to the end of the script."""
        with self._state.lock:
            self._state.script.extend(replies)

    def wait_for_requests(self, count: int, timeout: float) -> bool:
        """Whether ``count`` requests have arrived, waiting up to ``timeout`` seconds for them."""
        with self._state.arrived:
            return self._state.arrived.wait_for(lambda: len(self._state.requests) >= count, timeout)

    def wait_for_client_to_close(self, timeout: float) -> bool:
        """Whether a held or streaming response saw the client close within ``timeout``."""
        return self._state.closed_by_client.wait(timeout)

    def __enter__(self) -> "FakeEndpoint":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._state.stopping.set()
        self._server.shutdown()
        self._server.server_close()


# Building Messages API replies (anthropic-runner design D7): each event is an ``event:`` line, a
# ``data:`` line and a blank line, from message_start to message_stop.


def usage(
    input_tokens: int,
    output_tokens: int,
    cache_read: int | None = 0,
    cache_write: int | None = 0,
) -> dict[str, Any]:
    """A usage record as the Messages API reports it: input excludes both cache counters. A cache
    counter of None is left out, as a service that doesn't report it would."""
    used: dict[str, Any] = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    if cache_read is not None:
        used["cache_read_input_tokens"] = cache_read
    if cache_write is not None:
        used["cache_creation_input_tokens"] = cache_write
    return used


def event(kind: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"type": kind, **fields}


def sse(items: Iterable[dict[str, Any] | StreamItem]) -> list[StreamItem]:
    """Server-sent event lines for ``items``: each event as an ``event:`` line, a ``data:`` line and
    a blank line. Pauses, cuts, holds and gates pass through."""
    lines: list[StreamItem] = []
    for item in items:
        if isinstance(item, dict):
            lines += [f"event: {item['type']}", f"data: {json.dumps(item)}", ""]
        else:
            lines.append(item)
    return lines


def start(model: str = "fake-model", used: dict[str, Any] | None = None) -> dict[str, Any]:
    """The message_start event, with the input's usage."""
    return event(
        "message_start",
        message={
            "id": "msg_fake",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": used if used is not None else usage(10, 1),
        },
    )


def text_block(index: int, text: str) -> list[dict[str, Any]]:
    """A text block's events, its text in two deltas."""
    half = len(text) // 2
    return [
        event("content_block_start", index=index, content_block={"type": "text", "text": ""}),
        *[
            event("content_block_delta", index=index, delta={"type": "text_delta", "text": part})
            for part in (text[:half], text[half:])
            if part
        ],
        event("content_block_stop", index=index),
    ]


def thinking_block(index: int, thinking: str, signature: str = "sig-fake") -> list[dict[str, Any]]:
    """A thinking block's events, with its signature."""
    return [
        event(
            "content_block_start",
            index=index,
            content_block={"type": "thinking", "thinking": "", "signature": ""},
        ),
        event(
            "content_block_delta",
            index=index,
            delta={"type": "thinking_delta", "thinking": thinking},
        ),
        event(
            "content_block_delta",
            index=index,
            delta={"type": "signature_delta", "signature": signature},
        ),
        event("content_block_stop", index=index),
    ]


def tool_block(
    index: int, call_id: str | None, name: str | None, arguments: dict[str, Any] | str
) -> list[dict[str, Any]]:
    """A tool_use block's events, its input as JSON text in two deltas. ``call_id`` or ``name``
    None leaves it out."""
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    block: dict[str, Any] = {"type": "tool_use", "input": {}}
    if call_id is not None:
        block["id"] = call_id
    if name is not None:
        block["name"] = name
    half = len(raw) // 2
    return [
        event("content_block_start", index=index, content_block=block),
        *[
            event(
                "content_block_delta",
                index=index,
                delta={"type": "input_json_delta", "partial_json": part},
            )
            for part in (raw[:half], raw[half:])
        ],
        event("content_block_stop", index=index),
    ]


def finish(
    stop_reason: str | None,
    output_tokens: int = 5,
    **delta: Any,  # noqa: ANN401
) -> list[dict[str, Any]]:
    """message_delta with the stop reason and the output's usage, then message_stop."""
    return [
        event(
            "message_delta",
            delta={"stop_reason": stop_reason, "stop_sequence": None, **delta},
            usage={"output_tokens": output_tokens},
        ),
        event("message_stop"),
    ]


def text_reply(
    text: str,
    prompt: int = 10,
    completion: int = 5,
    stop_reason: str = "end_turn",
    model: str = "fake-model",
    gate: Gate | None = None,
    cache_read: int | None = 0,
    cache_write: int | None = 0,
) -> Reply:
    """A streamed reply that says ``text`` and stops."""
    return Reply(
        lines=sse(
            [
                start(model, usage(prompt, 1, cache_read, cache_write)),
                *([] if gate is None else [gate]),
                *text_block(0, text),
                *finish(stop_reason, completion),
            ]
        )
    )


def tool_reply(
    calls: Sequence[tuple[str | None, str | None, dict[str, Any] | str]],
    text: str | None = None,
    prompt: int = 10,
    completion: int = 5,
    thinking: str | None = None,
    model: str = "fake-model",
    cache_read: int | None = 0,
    cache_write: int | None = 0,
    stop_reason: str = "tool_use",
) -> Reply:
    """A streamed reply asking for ``calls``, each (call_id, name, arguments), after optional
    thinking and text."""
    items: list[dict[str, Any] | StreamItem] = [
        start(model, usage(prompt, 1, cache_read, cache_write))
    ]
    index = 0
    if thinking is not None:
        items += thinking_block(index, thinking)
        index += 1
    if text is not None:
        items += text_block(index, text)
        index += 1
    for call_id, name, arguments in calls:
        items += tool_block(index, call_id, name, arguments)
        index += 1
    items += finish(stop_reason, completion)
    return Reply(lines=sse(items))


def stream_error_reply(kind: str, text: str) -> Reply:
    """A stream that ends with an ``error`` event."""
    return Reply(lines=sse([start(), event("error", error={"type": kind, "message": text})]))


def error_body(kind: str, text: str) -> bytes:
    """A body in the Messages API's error shape."""
    return json.dumps({"type": "error", "error": {"type": kind, "message": text}}).encode()


def error_reply(
    status: int,
    text: str,
    kind: str = "invalid_request_error",
    headers: Sequence[tuple[str, str]] = (),
) -> Reply:
    """An HTTP error response in the Messages API's shape."""
    return Reply(status, headers=headers, body=error_body(kind, text))
