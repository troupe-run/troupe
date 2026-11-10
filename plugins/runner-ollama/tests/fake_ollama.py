"""A fake Ollama: a loopback HTTP server that plays scripted answers (local-model-runner design
D12).

It serves ``/api/version`` and ``/api/show`` from its settings, and each ``/api/chat`` request from
a queue of scripted answers: a status, lines (each with an optional delay before it), and
optionally a close part-way through, or silence. A built line names the model the request asked
for, as Ollama echoes it, unless the answer names another. It records every request's path and
body, and notices when a client closes a connection it is still answering. Standard library only,
so core's tests can copy it.
"""

import json
import selectors
import socket
import sys
import threading
import time
from collections import deque
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

POLL_SECONDS = 0.02


@dataclass(frozen=True)
class Line:
    """One line of a streamed answer, sent ``delay`` seconds after the one before."""

    data: bytes
    delay: float = 0.0


@dataclass(frozen=True)
class Answer:
    """One scripted answer to ``/api/chat``."""

    lines: Sequence[Line | bytes | dict[str, Any]] = ()
    status: int = 200
    body: bytes = b""
    """The body of an answer whose status isn't 200."""
    close_after: int | None = None
    """Close the connection after this many lines, without ending the answer."""
    silent: bool = False
    """After the lines, send nothing more until the client goes away or the server stops."""
    model: str | None = None
    """The model the answer's built lines name. None: the model the request asked for, as Ollama
    echoes it. Recorded lines (bytes) are sent as recorded."""

    def encoded(self, asked: object = None) -> list[Line]:
        named = self.model if self.model is not None else asked
        lines = []
        for line in self.lines:
            if isinstance(line, Line):
                lines.append(line)
            elif isinstance(line, bytes):
                lines.append(Line(line))
            else:
                if "model" in line and isinstance(named, str):
                    line = {**line, "model": named}
                lines.append(Line(json.dumps(line).encode()))
        return lines


def message(content: str = "", **fields: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON values
    """A streamed line holding part of an answer: content, and thinking or tool_calls."""
    return {
        "model": "fake",
        "created_at": "2026-11-04T00:00:00Z",
        "message": {"role": "assistant", "content": content, **fields},
        "done": False,
    }


def done(
    prompt: int | None = 10,
    generated: int | None = 5,
    reason: str = "stop",
    cached: int | None = None,
) -> dict[str, Any]:
    """An answer's last line, with its counts. ``cached`` is the prompt tokens Ollama took from
    its cache, part of ``prompt``; None leaves ``prompt_eval_cached_count`` out."""
    line: dict[str, Any] = {
        "model": "fake",
        "created_at": "2026-11-04T00:00:01Z",
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": reason,
        "total_duration": 1000,
    }
    if prompt is not None:
        line["prompt_eval_count"] = prompt
    if cached is not None:
        line["prompt_eval_cached_count"] = cached
    if generated is not None:
        line["eval_count"] = generated
    return line


def tool_call(name: str, arguments: object, index: int = 0) -> dict[str, Any]:
    """One entry of a message's tool_calls, as Ollama gives it: no id."""
    return {"function": {"index": index, "name": name, "arguments": arguments}}


def final(text: str, prompt: int = 10, generated: int = 5, cached: int | None = None) -> Answer:
    """An answer with only text: it ends the run."""
    return Answer([message(text), done(prompt, generated, cached=cached)])


def calls(
    *entries: dict[str, Any], prompt: int = 10, generated: int = 5, cached: int | None = None
) -> Answer:
    """An answer holding these tool calls."""
    return Answer([message("", tool_calls=list(entries)), done(prompt, generated, cached=cached)])


@dataclass
class Settings:
    version: str | None = "0.12.6"
    """None: /api/version answers 404."""
    version_body: bytes | None = None
    """Answer /api/version with these bytes instead."""
    models: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "fake": {
                "capabilities": ["completion", "tools"],
                "model_info": {"general.architecture": "fake", "fake.context_length": 40960},
            }
        }
    )
    """/api/show's answer for each model Ollama has; any other is 404."""
    silent_preflight: bool = False
    """Accept preflight requests and never answer them."""
    version_delay: float = 0.0
    """Answer /api/version this many seconds late."""
    silent_show: bool = False
    """Accept /api/show and never answer it."""


@dataclass(frozen=True)
class Request:
    path: str
    body: bytes
    at: float = field(default_factory=time.monotonic)
    """When the fake received it, by time.monotonic: a test can time what follows from here."""

    def json(self) -> Any:  # noqa: ANN401 - JSON
        return json.loads(self.body)


def _readable(sock: socket.socket, timeout: float) -> bool:
    """Whether ``sock`` has something to read (or has been closed), waiting up to ``timeout``.
    Not select.select: it refuses a descriptor of 1024 or more, which a long-lived test worker can
    hand the fake, and the handler then died without seeing the client's close (#301)."""
    with selectors.DefaultSelector() as selector:
        selector.register(sock, selectors.EVENT_READ)
        return bool(selector.select(timeout))


class _Server(ThreadingHTTPServer):
    def __init__(self, *args: Any) -> None:  # noqa: ANN401
        super().__init__(*args)
        self.unexpected: list[BaseException] = []

    def handle_error(self, request: Any, client_address: Any) -> None:  # noqa: ANN401
        """A client that resets its connection is a client the fake was told to expect: say
        nothing, rather than print a traceback. Any other error is kept, and fails the test when
        the fake stops: one swallowed here once hid why a close was never seen (#301)."""
        error = sys.exc_info()[1]
        if error is not None and not isinstance(error, ConnectionError):
            self.unexpected.append(error)


class FakeOllama:
    """The fake server, on 127.0.0.1 and a free port."""

    def __init__(self, answers: Sequence[Answer] = (), settings: Settings | None = None) -> None:
        self.settings = settings if settings is not None else Settings()
        self.answers: deque[Answer] = deque(answers)
        self.requests: list[Request] = []
        self.closed_by_client = threading.Event()
        """Set when a client closed a connection the fake was still answering."""
        self.stopping = threading.Event()
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:  # noqa: ANN401
                pass

            def do_GET(self) -> None:
                fake._record(self.path, b"")
                fake._get(self)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                fake._record(self.path, body)
                fake._post(self, body)

        self._server = _Server(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}"

    def start(self) -> "FakeOllama":
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop serving. Raises the first error a handler hit that wasn't a client resetting its
        connection, so a fake that broke can't pass for one that saw nothing."""
        self.stopping.set()
        self._server.shutdown()
        self._server.server_close()
        if self._server.unexpected:
            first = self._server.unexpected[0]
            raise AssertionError(f"the fake Ollama's handler failed: {first!r}") from first

    def chats(self) -> list[dict[str, Any]]:
        """The bodies of every /api/chat request, in order."""
        return [r.json() for r in self.requests if r.path == "/api/chat"]

    def chat_bodies(self) -> list[bytes]:
        """The exact bytes of every /api/chat request, in order."""
        return [r.body for r in self.requests if r.path == "/api/chat"]

    def _record(self, path: str, body: bytes) -> None:
        with self._lock:
            self.requests.append(Request(path, body))

    # Answering

    def _send(self, handler: BaseHTTPRequestHandler, status: int, body: bytes) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _hold(self, handler: BaseHTTPRequestHandler, seconds: float | None) -> bool:
        """Wait ``seconds`` (None: until the client goes or the server stops). False when the
        client closed the connection meanwhile."""
        deadline = None if seconds is None else time.monotonic() + seconds
        sock: socket.socket = handler.connection
        while deadline is None or time.monotonic() < deadline:
            if self.stopping.is_set():
                return False
            if _readable(sock, POLL_SECONDS):
                try:
                    peeked = sock.recv(1, socket.MSG_PEEK)
                except OSError:
                    peeked = b""
                if not peeked:
                    self.closed_by_client.set()
                    return False
        return True

    def _get(self, handler: BaseHTTPRequestHandler) -> None:
        settings = self.settings
        if handler.path != "/api/version":
            self._send(handler, 404, b'{"error": "not found"}')
        elif settings.silent_preflight:
            self._hold(handler, None)
        elif settings.version_delay and not self._hold(handler, settings.version_delay):
            return
        elif settings.version_body is not None:
            self._send(handler, 200, settings.version_body)
        elif settings.version is None:
            self._send(handler, 404, b"404 page not found")
        else:
            self._send(handler, 200, json.dumps({"version": settings.version}).encode())

    def _post(self, handler: BaseHTTPRequestHandler, body: bytes) -> None:
        if handler.path == "/api/show":
            if self.settings.silent_preflight or self.settings.silent_show:
                self._hold(handler, None)
                return
            model = json.loads(body).get("model")
            shown = self.settings.models.get(model)
            if shown is None:
                error = {"error": f"model '{model}' not found"}
                self._send(handler, 404, json.dumps(error).encode())
            else:
                self._send(handler, 200, json.dumps(shown).encode())
            return
        if handler.path != "/api/chat":
            self._send(handler, 404, b'{"error": "not found"}')
            return
        with self._lock:
            answer = self.answers.popleft() if self.answers else None
        if answer is None:
            self._send(handler, 500, b'{"error": "the fake has no answer left"}')
            return
        if answer.status != 200:
            self._send(handler, answer.status, answer.body)
            return
        try:
            asked = json.loads(body).get("model")
        except (ValueError, AttributeError):
            asked = None
        self._stream(handler, answer, asked)

    def _stream(self, handler: BaseHTTPRequestHandler, answer: Answer, asked: object) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", "application/x-ndjson")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.end_headers()
        try:
            for index, line in enumerate(answer.encoded(asked)):
                if answer.close_after is not None and index >= answer.close_after:
                    handler.close_connection = True
                    handler.connection.shutdown(socket.SHUT_RDWR)
                    return
                if line.delay and not self._hold(handler, line.delay):
                    return
                chunk = line.data + b"\n"
                handler.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                handler.wfile.flush()
            if answer.close_after is not None:
                handler.close_connection = True
                handler.connection.shutdown(socket.SHUT_RDWR)
                return
            if answer.silent:
                self._hold(handler, None)
                handler.close_connection = True
                return
            handler.wfile.write(b"0\r\n\r\n")
            handler.wfile.flush()
        except OSError:
            self.closed_by_client.set()
            handler.close_connection = True


@contextmanager
def serving(
    answers: Sequence[Answer] = (), settings: Settings | None = None
) -> Iterator[FakeOllama]:
    """A started fake, stopped afterwards."""
    fake = FakeOllama(answers, settings).start()
    try:
        yield fake
    finally:
        fake.stop()
