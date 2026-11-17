"""Ollama's API, through httpx2 (local-model-runner design D2, D4, D9; ollama-library design D1 to
D7). The one module that uses httpx2 or touches the network.

One Client talks to one endpoint. ``version`` and ``show`` are the preflight's requests. ``chat``
streams one ``/api/chat`` answer, line by line, as the bytes Ollama sent. ``close`` shuts the
request in flight from another thread, which wakes a blocked read on every platform (design D3).

httpx2 decides nothing for the runner (ollama-library design D3):

- **No redirect** is followed: a 3xx is a status like any other.
- **Nothing from the environment**: no proxy, no ``.netrc`` login, no certificate variables
  (``trust_env=False``), and no credential at all.
- **TLS** uses ``ssl.create_default_context()``, the context http.client used before.
- **No retries** of its own, and **no keep-alive**: each request has its own connection, which
  ``close`` can shut.
- **Its timeouts** are the runner's named settings, given with every request.
- **Bytes as sent**: ``Accept-Encoding: identity``, and each line split from the raw stream here,
  under ``LINE_MAX_BYTES``.

Closing the httpx2 client from another thread doesn't wake a read still waiting for Ollama's
answer (ollama-library design D4), so the client's transport is its own: httpcore2's connection
pool, on a network backend that records each socket it connects, which ``close`` shuts down.

Failures are classified here, so the conversation only decides what to do with them (design D9):
``RetryableError`` is a connection that failed or went silent, a line too long to read, or status
500, 502, 503 or 504; ``EngineError`` is any other status, which trying again won't change.
``StoppedError`` is a request closed by ``close``. A stream that stops without Ollama's last chunk
ends like a finished one, as http.client read it, so whether the answer ended is the conversation's
to tell, from Ollama's ``done`` line.
"""

import contextlib
import json
import socket
import ssl
import threading
from collections.abc import Generator, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import httpcore2
import httpx2

from troupe_runner_ollama.defaults import LINE_MAX_BYTES, STREAM_IDLE_TIMEOUT_SECONDS

RETRIED_STATUSES = (500, 502, 503, 504)
"""The statuses a request is made again for: the server's, which may pass (design D9)."""

ERROR_BODY_MAX_BYTES = 64 * 1024
"""The most of an error answer's body the client reads: enough for Ollama's {"error": ...}."""

PREFLIGHT_BODY_MAX_BYTES = ERROR_BODY_MAX_BYTES * 16
"""The most of a preflight answer's body the client reads: /api/show's, with the model's details."""

IDENTITY = "identity"
"""The only content encoding the client asks for and reads, so each line is the bytes Ollama
sent."""


class UnreachableError(Exception):
    """Ollama didn't answer at the endpoint, or answered with something that isn't Ollama."""


class StoppedError(Exception):
    """The request was closed by ``close``: the run is stopping."""


@dataclass
class RetryableError(Exception):
    """A failure worth another attempt, with the contract's retry reason."""

    reason: Literal["network", "server"]
    message: str
    body: bytes | None = None
    """The error answer's body, for the transcript, when there was one."""

    def __str__(self) -> str:
        return self.message


@dataclass
class EngineError(Exception):
    """An answer Ollama refused with a status that trying again won't change."""

    status: int
    message: str
    body: bytes

    def __str__(self) -> str:
        return self.message


def error_text(body: bytes, status: int | None = None) -> str:
    """The status, then Ollama's own message from an error body (``{"error": ...}``), or the body
    when it holds none: ``status 503: server busy``."""
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        text = str(data["error"])
    else:
        text = body.decode("utf-8", "replace").strip()
    prefix = "" if status is None else f"status {status}"
    return f"{prefix}: {text}" if prefix and text else prefix or text or "an empty answer"


# The transport (ollama-library design D4)


class _Sockets:
    """The sockets the client has connected, so ``close`` can shut down the one in flight."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: list[socket.socket] = []
        self._closed = False

    def add(self, sock: object) -> None:
        """Record ``sock``; shut it down at once if the client was closed while it connected."""
        if not isinstance(sock, socket.socket):
            return
        with self._lock:
            self._open = [s for s in self._open if s.fileno() != -1]
            self._open.append(sock)
            closed = self._closed
        if closed:
            _shut(sock)

    def close(self) -> None:
        """Shut down every socket still open, and any connected from now on."""
        with self._lock:
            self._closed = True
            sockets, self._open = self._open, []
        for sock in sockets:
            _shut(sock)


def _shut(sock: socket.socket) -> None:
    """Shut ``sock`` down without closing it: the thread reading it wakes with nothing to read and
    closes it itself. Closing it here would pull it out from under that read."""
    with contextlib.suppress(OSError):  # already closed, by either side
        sock.shutdown(socket.SHUT_RDWR)


class _RecordedStream(httpcore2.NetworkStream):
    """A connection's stream, recording the socket TLS wraps it in, which is a new one."""

    def __init__(self, inner: httpcore2.NetworkStream, sockets: _Sockets) -> None:
        self._inner = inner
        self._sockets = sockets

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._inner.read(max_bytes, timeout)

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._inner.write(buffer, timeout)

    def close(self) -> None:
        self._inner.close()

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore2.NetworkStream:
        stream = self._inner.start_tls(ssl_context, server_hostname, timeout)
        self._sockets.add(stream.get_extra_info("socket"))
        return _RecordedStream(stream, self._sockets)

    def get_extra_info(self, info: str) -> Any:  # noqa: ANN401 - httpcore2's own signature
        return self._inner.get_extra_info(info)


class _RecordingBackend(httpcore2.NetworkBackend):
    """httpcore2's own synchronous backend, recording each socket it connects."""

    def __init__(self, sockets: _Sockets) -> None:
        self._inner = httpcore2.SyncBackend()
        self._sockets = sockets

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore2.NetworkStream:
        stream = self._inner.connect_tcp(
            host,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )
        self._sockets.add(stream.get_extra_info("socket"))
        return _RecordedStream(stream, self._sockets)

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore2.NetworkStream:
        raise httpcore2.UnsupportedProtocol("the Ollama runner connects only over TCP")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


_EXCEPTIONS: tuple[tuple[type[Exception], type[httpx2.TransportError]], ...] = (
    (httpcore2.ConnectTimeout, httpx2.ConnectTimeout),
    (httpcore2.ReadTimeout, httpx2.ReadTimeout),
    (httpcore2.WriteTimeout, httpx2.WriteTimeout),
    (httpcore2.PoolTimeout, httpx2.PoolTimeout),
    (httpcore2.TimeoutException, httpx2.TimeoutException),
    (httpcore2.ConnectError, httpx2.ConnectError),
    (httpcore2.ReadError, httpx2.ReadError),
    (httpcore2.WriteError, httpx2.WriteError),
    (httpcore2.NetworkError, httpx2.NetworkError),
    (httpcore2.UnsupportedProtocol, httpx2.UnsupportedProtocol),
    (httpcore2.LocalProtocolError, httpx2.LocalProtocolError),
    (httpcore2.RemoteProtocolError, httpx2.RemoteProtocolError),
    (httpcore2.ProtocolError, httpx2.ProtocolError),
)
"""httpcore2's exceptions and httpx2's for each, most specific first, as httpx2's own transport
maps them."""


@contextlib.contextmanager
def _mapped() -> Iterator[None]:
    """Raise httpcore2's exceptions as httpx2's, so the rest of the client catches httpx2's only."""
    try:
        yield
    except httpcore2.ProxyError:  # pragma: no cover - the pool is given no proxy
        raise
    except Exception as error:
        for source, target in _EXCEPTIONS:
            if isinstance(error, source):
                raise target(str(error)) from error
        raise


class _ResponseStream(httpx2.SyncByteStream):
    def __init__(self, stream: Iterable[bytes]) -> None:
        self._stream = stream

    def __iter__(self) -> Iterator[bytes]:
        with _mapped():
            yield from self._stream

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()


class _Transport(httpx2.BaseTransport):
    """httpx2's own HTTP transport, on a recording backend (ollama-library design D4)."""

    def __init__(self, sockets: _Sockets) -> None:
        self._pool = httpcore2.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            max_keepalive_connections=0,
            retries=0,
            network_backend=_RecordingBackend(sockets),
        )

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        if not isinstance(request.stream, httpx2.SyncByteStream):  # pragma: no cover
            raise TypeError("the Ollama runner's transport is synchronous")
        core = httpcore2.Request(
            method=request.method,
            url=httpcore2.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        with _mapped():
            response = self._pool.handle_request(core)
        if not isinstance(response.stream, Iterable):  # pragma: no cover
            raise TypeError("httpcore2's synchronous pool answered with an asynchronous stream")
        return httpx2.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_ResponseStream(response.stream),
            extensions=response.extensions,
        )

    def close(self) -> None:
        self._pool.close()


# The client


_FAILURES = (httpx2.TransportError, httpx2.InvalidURL, httpx2.StreamError, OSError, ValueError)
"""What a request can fail with: httpx2's errors, and a host name the resolver refuses
(UnicodeError, a ValueError)."""


class Client:
    """Ollama's API at one endpoint."""

    def __init__(
        self,
        endpoint: str,
        *,
        idle_timeout: float = STREAM_IDLE_TIMEOUT_SECONDS,
        line_max_bytes: int = LINE_MAX_BYTES,
    ) -> None:
        try:
            parts = urlsplit(endpoint)
            parts.port  # noqa: B018 - raises for a port that isn't one
        except ValueError as error:  # a bracketed host that isn't an IPv6 address
            raise UnreachableError(
                f"{endpoint} isn't an address Ollama can be reached at: {error}"
            ) from error
        if parts.hostname is None:
            raise UnreachableError(f"{endpoint} has no host")
        self.endpoint = endpoint
        self._idle_timeout = idle_timeout
        self._line_max_bytes = line_max_bytes
        self._lock = threading.Lock()
        self._closed = False
        self._sockets = _Sockets()
        try:
            self._http = httpx2.Client(
                base_url=f"{parts.scheme}://{parts.netloc}",
                transport=_Transport(self._sockets),
                trust_env=False,
                follow_redirects=False,
                headers={"Accept-Encoding": IDENTITY},
                timeout=httpx2.Timeout(idle_timeout),
            )
        except (httpx2.InvalidURL, ValueError) as error:
            raise UnreachableError(
                f"{endpoint} isn't an address Ollama can be reached at: {error}"
            ) from error

    def close(self) -> None:
        """Close the request in flight, and refuse any later one. Safe from any thread."""
        with self._lock:
            self._closed = True
        self._sockets.close()

    @property
    def closed(self) -> bool:
        return self._closed

    def _check_open(self) -> None:
        with self._lock:
            if self._closed:
                raise StoppedError

    def _send(self, method: str, path: str, body: bytes | None, timeout: float) -> httpx2.Response:
        """The response to one request, with its body still to read."""
        self._check_open()
        headers = {} if body is None else {"Content-Type": "application/json"}
        request = self._http.build_request(
            method, path, content=body, headers=headers, timeout=httpx2.Timeout(timeout)
        )
        return self._http.send(request, stream=True)

    def _get_json(self, method: str, path: str, body: object, timeout: float) -> tuple[int, bytes]:
        payload = None if body is None else json.dumps(body).encode()
        try:
            response = self._send(method, path, payload, timeout)
            try:
                return response.status_code, _read(response, PREFLIGHT_BODY_MAX_BYTES)
            finally:
                response.close()
        except _FAILURES as error:
            if self._closed:
                raise StoppedError from error
            raise UnreachableError(f"{type(error).__name__}: {error}") from error

    def version(self, timeout: float) -> str:
        """Ollama's version (``GET /api/version``). Raises UnreachableError."""
        status, body = self._get_json("GET", "/api/version", None, timeout)
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get("version"), str):
            raise UnreachableError(
                f"/api/version answered status {status} without Ollama's version"
            )
        return str(data["version"])

    def show(self, model: str, timeout: float) -> dict[str, Any] | None:
        """The model's details (``POST /api/show``), or None when Ollama has no such model.
        Raises UnreachableError."""
        status, body = self._get_json("POST", "/api/show", {"model": model}, timeout)
        if status == 404:
            return None
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if status != 200 or not isinstance(data, dict):
            raise UnreachableError(f"/api/show answered {error_text(body, status)}")
        return data

    def chat(self, body: bytes) -> Generator[bytes]:
        """Stream one ``/api/chat`` answer to ``body``, the request's exact bytes. Yields each line
        without its line ending, until Ollama ends the answer. Raises RetryableError, EngineError or
        StoppedError."""
        try:
            response = self._send("POST", "/api/chat", body, self._idle_timeout)
        except StoppedError:
            raise
        except httpx2.TimeoutException as error:
            raise self._failed(f"Ollama sent nothing for {self._idle_timeout:g}s") from error
        except _FAILURES as error:
            raise self._failed(f"couldn't reach Ollama: {error}") from error
        try:
            if response.status_code != 200:
                error_body = self._read_error(response)
                message = f"Ollama answered {error_text(error_body, response.status_code)}"
                if response.status_code in RETRIED_STATUSES:
                    raise RetryableError("server", message, error_body)
                raise EngineError(response.status_code, message, error_body)
            encoding = response.headers.get("Content-Encoding", IDENTITY).strip().lower()
            if encoding != IDENTITY:
                raise RetryableError(
                    "network",
                    f"Ollama sent its answer encoded as {encoding!r}, though the runner asked "
                    "for it unencoded",
                )
            yield from self._lines(response)
        finally:
            response.close()

    def _read_error(self, response: httpx2.Response) -> bytes:
        try:
            return _read(response, ERROR_BODY_MAX_BYTES)
        except _FAILURES as error:
            raise self._failed(f"the connection failed reading Ollama's error: {error}") from error

    def _lines(self, response: httpx2.Response) -> Iterator[bytes]:
        """Each line of ``response``, split from the bytes as they came, none read past
        ``line_max_bytes``. A stream cut short ends the lines, as http.client read it."""
        limit = self._line_max_bytes
        pending = b""
        chunks = response.iter_raw()
        while True:
            try:
                chunk = next(chunks, None)
            except httpx2.TimeoutException as error:
                raise self._failed(f"Ollama sent nothing for {self._idle_timeout:g}s") from error
            except httpx2.RemoteProtocolError as error:
                if self._closed:
                    raise StoppedError from error
                chunk = None  # the stream ended before Ollama's last chunk
            except _FAILURES as error:
                raise self._failed(f"the connection dropped: {error}") from error
            if self._closed:
                raise StoppedError
            if chunk is None:
                if pending:
                    yield pending.rstrip(b"\r")
                return
            pending += chunk
            while (end := pending.find(b"\n")) != -1:
                line, pending = pending[:end], pending[end + 1 :]
                if len(line) > limit:
                    raise self._too_long()
                yield line.rstrip(b"\r")
                if self._closed:
                    raise StoppedError
            if len(pending) > limit:
                raise self._too_long()

    def _too_long(self) -> RetryableError:
        return RetryableError(
            "network", f"Ollama sent a line longer than {self._line_max_bytes} bytes"
        )

    def _failed(self, message: str) -> Exception:
        """A connection failure: StoppedError when ``close`` caused it, else a network retry."""
        if self._closed:
            return StoppedError()
        return RetryableError("network", message)


def _read(response: httpx2.Response, limit: int) -> bytes:
    """At most ``limit`` bytes of ``response``'s body, as sent."""
    data = b""
    for chunk in response.iter_raw():
        data += chunk
        if len(data) >= limit:
            return data[:limit]
    return data
