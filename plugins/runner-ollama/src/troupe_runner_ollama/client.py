"""Ollama's API, on the standard library's http.client (local-model-runner design D2, D4, D9).

One Client talks to one endpoint. ``version`` and ``show`` are the preflight's requests. ``chat``
streams one ``/api/chat`` answer, line by line. ``close`` shuts the request in flight from another
thread, which wakes a blocked read on every platform (design D3).

Failures are classified here, so the conversation only decides what to do with them (design D9):
``RetryableError`` is a connection that failed or went silent, a line too long to read, or status
500, 502, 503 or 504; ``EngineError`` is any other status, which trying again won't change.
``StoppedError`` is a request closed by ``close``. A stream that stops without Ollama's last chunk
ends like a finished one (http.client reads both as the end), so whether the answer ended is the
conversation's to tell, from Ollama's ``done`` line.
"""

import contextlib
import http.client
import json
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from troupe_runner_ollama.defaults import LINE_MAX_BYTES, STREAM_IDLE_TIMEOUT_SECONDS

RETRIED_STATUSES = (500, 502, 503, 504)
"""The statuses a request is made again for: the server's, which may pass (design D9)."""

ERROR_BODY_MAX_BYTES = 64 * 1024
"""The most of an error answer's body the client reads: enough for Ollama's {"error": ...}."""


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
    """Ollama's own message from an error body (``{"error": ...}``), or the status and the body
    when it holds none."""
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        return str(data["error"])
    text = body.decode("utf-8", "replace").strip()
    prefix = "" if status is None else f"status {status}"
    return f"{prefix}: {text}" if prefix and text else prefix or text or "an empty answer"


class Client:
    """Ollama's API at one endpoint."""

    def __init__(
        self,
        endpoint: str,
        *,
        idle_timeout: float = STREAM_IDLE_TIMEOUT_SECONDS,
        line_max_bytes: int = LINE_MAX_BYTES,
    ) -> None:
        parts = urlsplit(endpoint)
        if parts.hostname is None:
            raise ValueError(f"{endpoint!r} has no host")
        self.endpoint = endpoint
        self._https = parts.scheme == "https"
        self._host = parts.hostname
        self._port = parts.port
        self._idle_timeout = idle_timeout
        self._line_max_bytes = line_max_bytes
        self._lock = threading.Lock()
        self._connection: http.client.HTTPConnection | None = None
        self._closed = False

    def _connect(self, timeout: float) -> http.client.HTTPConnection:
        with self._lock:
            if self._closed:
                raise StoppedError
            connection = (
                http.client.HTTPSConnection(self._host, self._port, timeout=timeout)
                if self._https
                else http.client.HTTPConnection(self._host, self._port, timeout=timeout)
            )
            self._connection = connection
            return connection

    def _done(self, connection: http.client.HTTPConnection) -> None:
        with self._lock:
            if self._connection is connection:
                self._connection = None
        connection.close()

    def close(self) -> None:
        """Close the request in flight, and refuse any later one. Safe from any thread."""
        with self._lock:
            self._closed = True
            connection = self._connection
            self._connection = None
        if connection is None:
            return
        if connection.sock is None:
            connection.close()  # not connected yet: nothing is reading it
            return
        # Only shut the socket down: the thread reading it wakes with nothing to read, and closes
        # the connection itself. Closing it here would pull the response out from under that read.
        with contextlib.suppress(OSError):  # already closed by the other side
            connection.sock.shutdown(socket.SHUT_RDWR)

    @property
    def closed(self) -> bool:
        return self._closed

    def _get_json(self, method: str, path: str, body: object, timeout: float) -> tuple[int, bytes]:
        connection = self._connect(timeout)
        try:
            payload = None if body is None else json.dumps(body).encode()
            headers = {} if payload is None else {"Content-Type": "application/json"}
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            return response.status, response.read(ERROR_BODY_MAX_BYTES * 16)
        except (OSError, http.client.HTTPException) as error:
            if self._closed:
                raise StoppedError from error
            raise UnreachableError(f"{type(error).__name__}: {error}") from error
        finally:
            self._done(connection)

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

    def chat(self, body: bytes) -> Iterator[bytes]:
        """Stream one ``/api/chat`` answer to ``body``, the request's exact bytes. Yields each line
        without its line ending, until Ollama ends the answer. Raises RetryableError, EngineError or
        StoppedError."""
        connection = self._connect(self._idle_timeout)
        try:
            try:
                connection.request(
                    "POST", "/api/chat", body=body, headers={"Content-Type": "application/json"}
                )
                response = connection.getresponse()
            except TimeoutError as error:
                raise self._failed(f"Ollama sent nothing for {self._idle_timeout:g}s") from error
            except (OSError, http.client.HTTPException) as error:
                raise self._failed(f"couldn't reach Ollama: {error}") from error
            if response.status != 200:
                error_body = self._read_error(response)
                message = f"Ollama answered {error_text(error_body, response.status)}"
                if response.status in RETRIED_STATUSES:
                    raise RetryableError("server", message, error_body)
                raise EngineError(response.status, message, error_body)
            yield from self._lines(response)
        finally:
            self._done(connection)

    def _read_error(self, response: http.client.HTTPResponse) -> bytes:
        try:
            return response.read(ERROR_BODY_MAX_BYTES)
        except (OSError, http.client.HTTPException) as error:
            raise self._failed(f"the connection failed reading Ollama's error: {error}") from error

    def _lines(self, response: http.client.HTTPResponse) -> Iterator[bytes]:
        while True:
            try:
                line = response.readline(self._line_max_bytes + 1)
            except TimeoutError as error:
                raise self._failed(f"Ollama sent nothing for {self._idle_timeout:g}s") from error
            except (OSError, http.client.HTTPException) as error:
                raise self._failed(f"the connection dropped: {error}") from error
            if self._closed:
                raise StoppedError
            if not line:
                return
            if len(line) > self._line_max_bytes:
                raise RetryableError(
                    "network", f"Ollama sent a line longer than {self._line_max_bytes} bytes"
                )
            yield line.rstrip(b"\r\n")

    def _failed(self, message: str) -> Exception:
        """A connection failure: StoppedError when ``close`` caused it, else a network retry."""
        if self._closed:
            return StoppedError()
        return RetryableError("network", message)
