"""A fake Responses API service for the OpenAI runner's tests (openai-style-runner design
D13).

It listens on 127.0.0.1, answers each request with the next reply from its script, and records
every request it got, headers included, so a test can check what the runner sent. A reply is a
status, headers and a body, or a stream of server-sent event lines that can pause, stop short or be
held open until the client goes away.

    with FakeEndpoint([text_reply("Done."), Reply(500)]) as fake:
        fake.endpoint      # http://127.0.0.1:<port>/v1
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


StreamItem = str | Pause | Cut | Hold


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
    """A fake Responses API service, answering from ``script`` in order."""

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
        """The base URL a runtime names: requests go to its /responses."""
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}/v1"

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


# Building Responses API replies (openai-style-runner design D4, D15): each event is an ``event:``
# line, a ``data:`` line and a blank line, with no [DONE]; the final event carries the whole
# response.


def usage(
    input_tokens: int,
    output_tokens: int,
    cached: int | None = 0,
    cache_write: int | None = None,
    **more: Any,  # noqa: ANN401
) -> dict[str, Any]:
    """A usage record as the Responses API reports it; ``cache_write`` as OpenAI adds it.
    ``cached=None`` leaves ``cached_tokens`` out, as a service that doesn't report it would."""
    details: dict[str, Any] = {}
    if cached is not None:
        details["cached_tokens"] = cached
    if cache_write is not None:
        details["cache_write_tokens"] = cache_write
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": details,
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": input_tokens + output_tokens,
        **more,
    }


def message(text: str) -> dict[str, Any]:
    """An output message item holding ``text``."""
    return {
        "id": "msg_fake",
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def refusal(text: str) -> dict[str, Any]:
    """An output message item holding a refusal."""
    return {
        "id": "msg_fake",
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "refusal", "refusal": text}],
    }


def function_call(
    call_id: str | None, name: str, arguments: dict[str, Any] | str
) -> dict[str, Any]:
    """A function_call output item; ``call_id`` None leaves it out."""
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    item: dict[str, Any] = {
        "id": f"fc_{call_id or 'none'}",
        "type": "function_call",
        "status": "completed",
        "name": name,
        "arguments": raw,
    }
    if call_id is not None:
        item["call_id"] = call_id
    return item


def reasoning(summary: str) -> dict[str, Any]:
    """A reasoning output item, with encrypted content to send back."""
    return {
        "id": "rs_fake",
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": summary}],
        "encrypted_content": "opaque-reasoning",
    }


def response(
    output: list[dict[str, Any]],
    status: str = "completed",
    used: dict[str, Any] | None = None,
    model: str = "fake-model",
    incomplete: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A response object, as a final event carries it."""
    return {
        "id": "resp_fake",
        "object": "response",
        "status": status,
        "model": model,
        "output": output,
        "incomplete_details": None if incomplete is None else {"reason": incomplete},
        "error": error,
        "usage": used,
    }


def event(kind: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"type": kind, **fields}


def sse(items: Iterable[dict[str, Any] | StreamItem]) -> list[StreamItem]:
    """Server-sent event lines for ``items``: each event as an ``event:`` line, a ``data:`` line and
    a blank line. Pauses, cuts and holds pass through."""
    lines: list[StreamItem] = []
    for item in items:
        if isinstance(item, dict):
            lines += [f"event: {item['type']}", f"data: {json.dumps(item)}", ""]
        else:
            lines.append(item)
    return lines


def _created() -> dict[str, Any]:
    return event("response.created", response=response([], status="in_progress"))


def final(
    output: list[dict[str, Any]],
    status: str = "completed",
    used: dict[str, Any] | None = None,
    **fields: Any,  # noqa: ANN401
) -> dict[str, Any]:
    """The final event for a response with ``output``."""
    return event(f"response.{status}", response=response(output, status, used, **fields))


def text_reply(text: str, prompt: int = 10, completion: int = 5) -> Reply:
    """A streamed reply that says ``text`` and completes, with usage."""
    return Reply(
        lines=sse(
            [
                _created(),
                event("response.output_text.delta", delta=text, output_index=0),
                final([message(text)], used=usage(prompt, completion)),
            ]
        )
    )


def tool_reply(
    calls: Sequence[tuple[str | None, str, dict[str, Any] | str]],
    text: str | None = None,
    prompt: int = 10,
    completion: int = 5,
    before: Sequence[dict[str, Any]] = (),
) -> Reply:
    """A streamed reply asking for ``calls``, each (call_id, name, arguments), after any ``before``
    output items and optional text. Each call's arguments stream as two deltas."""
    output = [*before, *([message(text)] if text else [])]
    items: list[dict[str, Any] | StreamItem] = [_created()]
    for index, (call_id, name, arguments) in enumerate(calls):
        item = function_call(call_id, name, arguments)
        output.append(item)
        half = len(item["arguments"]) // 2
        items.append(
            event("response.output_item.added", item={**item, "arguments": ""}, output_index=index)
        )
        for part in (item["arguments"][:half], item["arguments"][half:]):
            items.append(
                event("response.function_call_arguments.delta", delta=part, output_index=index)
            )
    items.append(final(output, used=usage(prompt, completion)))
    return Reply(lines=sse(items))


def status_reply(
    status: str,
    output: list[dict[str, Any]] | None = None,
    **fields: Any,  # noqa: ANN401
) -> Reply:
    """A streamed reply whose final event has ``status`` (incomplete, failed or another)."""
    return Reply(lines=sse([_created(), final(output or [], status, usage(10, 5), **fields)]))


def error_event_reply(code: str, text: str) -> Reply:
    """A stream that ends with an error event."""
    return Reply(lines=sse([_created(), event("error", code=code, message=text)]))


def error_reply(
    status: int,
    text: str,
    code: str | None = None,
    kind: str = "invalid_request_error",
    headers: Sequence[tuple[str, str]] = (),
) -> Reply:
    """An HTTP error response in OpenAI's shape."""
    body = {"error": {"message": text, "type": kind, "param": None, "code": code}}
    return Reply(status, headers=headers, body=json.dumps(body).encode("utf-8"))
