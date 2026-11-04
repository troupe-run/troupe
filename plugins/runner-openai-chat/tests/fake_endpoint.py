"""A fake Chat Completions service for the OpenAI-style runner's tests (openai-style-runner design
D13).

It listens on 127.0.0.1, answers each request with the next reply from its script, and records
every request it got, headers included, so a test can check what the runner sent. A reply is a
status, headers and a body, or a stream of server-sent event lines that can pause, stop short or be
held open until the client goes away.

    with FakeEndpoint([stream(text_chunks("Done.")), Reply(500)]) as fake:
        fake.endpoint      # http://127.0.0.1:<port>/v1
        fake.requests      # each Request: method, path, headers, body

Self-contained: the standard library only.
"""

import json
import select
import socket
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ENDED = "[DONE]"


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


def _client_gone(connection: socket.socket) -> bool:
    readable, _, _ = select.select([connection], [], [], 0)
    if not readable:
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
        if reply.lines is None:
            body = reply.body or b""
            if not any(name.lower() == "content-type" for name, _ in reply.headers):
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        for item in reply.lines:
            if isinstance(item, Pause):
                time.sleep(item.seconds)
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
    """A fake Chat Completions service, answering from ``script`` in order."""

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
        """The base URL a runtime names: requests go to its /chat/completions."""
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


# Building replies


def chunk(
    delta: dict[str, Any] | None = None,
    finish: str | None = None,
    model: str = "fake-model",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One chat.completion.chunk: a delta for choice 0 and its finish reason, or (with no delta and
    no finish) the final usage chunk, whose choices are empty."""
    choices = (
        []
        if delta is None and finish is None
        else [{"index": 0, "delta": delta or {}, "finish_reason": finish}]
    )
    data: dict[str, Any] = {
        "id": "chatcmpl-fake",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": model,
        "choices": choices,
    }
    if usage is not None:
        data["usage"] = usage
    return data


def usage(prompt: int, completion: int, cached: int = 0, **more: Any) -> dict[str, Any]:  # noqa: ANN401
    """A usage record as OpenAI reports it."""
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "prompt_tokens_details": {"cached_tokens": cached},
        **more,
    }


def sse(chunks: Iterable[dict[str, Any] | StreamItem], done: bool = True) -> list[StreamItem]:
    """Server-sent event lines for ``chunks``: each a ``data:`` line and a blank line, then
    ``data: [DONE]`` unless ``done`` is false. Pauses, cuts and holds pass through."""
    lines: list[StreamItem] = []
    for item in chunks:
        if isinstance(item, dict):
            lines += [f"data: {json.dumps(item)}", ""]
        else:
            lines.append(item)
    if done:
        lines += [f"data: {ENDED}", ""]
    return lines


def text_reply(text: str, prompt: int = 10, completion: int = 5) -> Reply:
    """A streamed reply that says ``text`` and stops, with usage."""
    return Reply(
        lines=sse(
            [
                chunk({"role": "assistant", "content": ""}),
                chunk({"content": text}),
                chunk(finish="stop"),
                chunk(usage=usage(prompt, completion)),
            ]
        )
    )


def tool_reply(
    calls: Sequence[tuple[str, str, dict[str, Any] | str]],
    text: str | None = None,
    prompt: int = 10,
    completion: int = 5,
) -> Reply:
    """A streamed reply asking for ``calls``, each (id, name, arguments), with optional text."""
    chunks: list[dict[str, Any] | StreamItem] = [chunk({"role": "assistant", "content": None})]
    if text:
        chunks.append(chunk({"content": text}))
    for index, (call_id, name, arguments) in enumerate(calls):
        raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
        head: dict[str, Any] = {"index": index, "type": "function", "function": {"name": name}}
        if call_id:
            head["id"] = call_id
        half = len(raw) // 2
        chunks.append(
            chunk({"tool_calls": [{**head, "function": {"name": name, "arguments": raw[:half]}}]})
        )
        chunks.append(
            chunk({"tool_calls": [{"index": index, "function": {"arguments": raw[half:]}}]})
        )
    chunks += [chunk(finish="tool_calls"), chunk(usage=usage(prompt, completion))]
    return Reply(lines=sse(chunks))


def error_reply(
    status: int,
    message: str,
    code: str | None = None,
    kind: str = "invalid_request_error",
    headers: Sequence[tuple[str, str]] = (),
) -> Reply:
    """An error response in OpenAI's shape."""
    body = {"error": {"message": message, "type": kind, "param": None, "code": code}}
    return Reply(status, headers=headers, body=json.dumps(body).encode("utf-8"))
