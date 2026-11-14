"""The one module that uses the anthropic package (anthropic-runner design D1, D4, D10).

Everything the library decides for itself, the runner decides here instead:

- **Its HTTP client** is the runner's own ``httpx2.Client``: it follows no redirect (the library's
  own client follows them), its timeouts are the runner's named settings (the library's default is
  ten minutes), and it reads only the proxy and certificate variables troupe passes the runner.
- **Its retries** are off (``max_retries=0``): the runner retries in its own loop (exchange.py).
- **Its credential** is the runtime's, given explicitly, or none at all. The client is a subclass
  of the library's, which the library treats as having its own auth and never searches the
  environment or the disk for one, and with no credential ``Authorization`` is omitted.
- **Its environment.** The library reads ``ANTHROPIC_CUSTOM_HEADERS`` even when it's given
  headers, and ``ANTHROPIC_BASE_URL``, keys and profiles when it isn't given them, so the runner
  removes every ``ANTHROPIC_*`` variable from its own environment before it builds the client.
- **Its logging and tracing.** Its loggers pass only warnings to standard error, cut to fit, never
  to standard output, whatever ``ANTHROPIC_LOG`` says; its OpenTelemetry spans are off.

The rest of the runner sees plain data: a request's parameters as a dict, each stream event as the
library parsed it (``to_dict``), and one of a closed set of failures.
"""

import json
import logging
import os
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

import anthropic
import httpx2

from troupe_runner_anthropic.defaults import (
    CONNECT_TIMEOUT_SECONDS,
    LIBRARY_LOG_MAX_BYTES,
    STREAM_TIMEOUT_SECONDS,
    WRITE_TIMEOUT_SECONDS,
)
from troupe_runner_anthropic.runtime import Runtime

LIBRARY_PREFIX: Final = "ANTHROPIC_"
"""The prefix of every environment variable the library reads (design D4)."""

LIBRARY_LOGGERS: Final = ("anthropic", "httpx2", "httpcore2")
"""The library's loggers, and its HTTP client's."""

STREAM_TYPE: Final = "text/event-stream"
"""The media type a streamed reply is sent as, which the runner asks for."""


def clear_library_environment(
    environ: dict[str, str] | os._Environ[str] | None = None,
) -> list[str]:
    """Remove every ANTHROPIC_* variable from ``environ`` (the process's own by default), so the
    library can't read one; the names removed."""
    target = os.environ if environ is None else environ
    names = sorted(name for name in target if name.upper().startswith(LIBRARY_PREFIX))
    for name in names:
        del target[name]
    return names


class Writable(Protocol):
    """Where the library's warnings go: standard error, as text."""

    def write(self, text: str, /) -> int: ...

    def flush(self) -> None: ...


class _CutHandler(logging.Handler):
    """Writes a record's message to a text stream, one line, cut to LIBRARY_LOG_MAX_BYTES."""

    def __init__(self, stream: Writable, mask: Callable[[str], str]) -> None:
        super().__init__(logging.WARNING)
        self._stream = stream
        self._mask = mask

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = " ".join(self.format(record).split())
            data = self._mask(text).encode("utf-8", "backslashreplace")
            if len(data) > LIBRARY_LOG_MAX_BYTES:
                left = len(data) - LIBRARY_LOG_MAX_BYTES
                text = data[:LIBRARY_LOG_MAX_BYTES].decode("utf-8", "ignore")
                text += f"… ({left} bytes left out)"
            else:
                text = data.decode("utf-8")
            self._stream.write(f"anthropic runner: library {record.levelname.lower()}: {text}\n")
            self._stream.flush()
        except Exception:  # logging must never fail the run
            self.handleError(record)


def quiet_library_logging(mask: Callable[[str], str], stream: Writable | None = None) -> None:
    """Keep the library's loggers off standard output: warnings and above to ``stream`` (standard
    error), masked and cut, and nothing below them, whatever ANTHROPIC_LOG asked for."""
    handler = _CutHandler(sys.stderr if stream is None else stream, mask)
    for name in LIBRARY_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.setLevel(logging.WARNING)
        logger.propagate = False


# Failures


class ServiceError(Exception):
    """A request that failed: one of the closed set below."""


class StatusError(ServiceError):
    """The service answered with a status other than 2xx, or sent an ``error`` event in its stream
    (``in_stream``; its status is then the stream's 200)."""

    def __init__(
        self,
        status: int,
        headers: Mapping[str, str],
        body: bytes,
        error_type: str | None,
        message: str | None,
        in_stream: bool = False,
    ) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.headers = {name.lower(): value for name, value in headers.items()}
        """By lower-case name."""
        self.body = body
        self.error_type = error_type
        """The Messages API's ``error.type``, such as ``overloaded_error``, when the body has it."""
        self.message = message
        """The service's own message, when the body has one."""
        self.in_stream = in_stream


class NotAStreamError(ServiceError):
    """A 2xx whose Content-Type is present and isn't a stream."""

    def __init__(self, status: int, content_type: str, body: bytes) -> None:
        super().__init__(f"HTTP {status} {content_type}")
        self.status = status
        self.content_type = content_type
        self.body = body


class NetworkError(ServiceError):
    """No answer: the connection failed, broke, or went quiet past a timeout."""


class UnreadableError(ServiceError):
    """The service sent something the library can't read, such as an event that isn't JSON."""


def _error_of(body: object) -> tuple[str | None, str | None]:
    """The error's type and message, from a body in the Messages API's error shape."""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            kind, message = error.get("type"), error.get("message")
            return (
                kind if isinstance(kind, str) else None,
                message if isinstance(message, str) else None,
            )
        if isinstance(error, str):
            return None, error
    return None, None


def _body_bytes(body: object, response: httpx2.Response | None) -> bytes:
    if body is not None and not isinstance(body, str | bytes):
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    if response is not None:
        try:
            return response.content
        except httpx2.HTTPError:
            return b""
    return b""


# The client


class _RunnerClient(anthropic.Anthropic):
    """The library's client, as a subclass: the library runs no credential discovery for one
    (anthropic 2.8.0, ``_is_base_client``), so the runner's credential, or none, is all it has."""


@dataclass(frozen=True)
class Opened:
    """A response whose status was 2xx and whose stream is being read."""

    status: int
    headers: dict[str, str]
    """By lower-case name."""
    events: Iterator[dict[str, Any]]
    """Each stream event as the library parsed it."""


class Service:
    """One run's connection to its service."""

    def __init__(
        self,
        runtime: Runtime,
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
        stream_timeout: float = STREAM_TIMEOUT_SECONDS,
        write_timeout: float = WRITE_TIMEOUT_SECONDS,
    ) -> None:
        clear_library_environment()
        timeout = httpx2.Timeout(
            connect=connect_timeout,
            read=stream_timeout,
            write=write_timeout,
            pool=connect_timeout,
        )
        self._http = httpx2.Client(follow_redirects=False, timeout=timeout)
        credential: dict[str, Any] = (
            {"api_key": runtime.credential}
            if runtime.credential is not None
            else {"default_headers": {"Authorization": anthropic.Omit()}}
        )
        self._client = _RunnerClient(
            base_url=runtime.endpoint.url,
            max_retries=0,
            timeout=timeout,
            http_client=self._http,
            open_telemetry=False,
            **credential,
        )

    def close(self) -> None:
        self._http.close()

    def stream(self, params: Mapping[str, Any]) -> Opened:
        """Send one request, streamed, and return its response once its status is in. Raises
        StatusError, NotAStreamError or NetworkError; the events it yields raise those,
        UnreadableError, or NetworkError for a stream that breaks."""
        try:
            stream = self._client.messages.create(**params, stream=True)
        except anthropic.APIStatusError as error:
            kind, message = _error_of(error.body)
            raise StatusError(
                error.status_code,
                error.response.headers,
                _body_bytes(error.body, error.response),
                kind,
                message,
            ) from None
        except anthropic.APIConnectionError as error:  # timeouts included
            raise NetworkError(_said(error)) from None
        except httpx2.HTTPError as error:
            raise NetworkError(_said(error)) from None
        response = stream.response
        headers = {name.lower(): value for name, value in response.headers.items()}
        said = headers.get("content-type")
        if said is not None and said.partition(";")[0].strip().lower() != STREAM_TYPE:
            try:
                body = response.read()
            except httpx2.HTTPError:
                body = b""
            finally:
                stream.close()
            raise NotAStreamError(response.status_code, said, body)
        return Opened(response.status_code, headers, _events(stream))


def _said(error: BaseException) -> str:
    """A network failure in words, with its cause when the library wraps one."""
    cause = error.__cause__ or error.__context__
    text = f"{type(error).__name__}: {error}"
    if cause is not None and str(cause) and str(cause) not in text:
        text += f" ({type(cause).__name__}: {cause})"
    return text


def _events(stream: Any) -> Iterator[dict[str, Any]]:  # noqa: ANN401 - the library's Stream
    """Each event of ``stream`` as a dict, with the library's failures as the runner's."""
    try:
        for event in stream:
            yield event.to_dict(mode="json")
    except anthropic.APIStatusError as error:  # an error event in the stream
        kind, message = _error_of(error.body)
        raise StatusError(
            error.status_code,
            error.response.headers,
            _body_bytes(error.body, None),
            kind,
            message,
            in_stream=True,
        ) from None
    except (anthropic.APIConnectionError, httpx2.HTTPError) as error:
        raise NetworkError(_said(error)) from None
    except ValueError as error:  # an event's data that isn't JSON
        raise UnreadableError(f"an event in the reply isn't JSON ({error})") from None
    finally:
        stream.close()


__all__ = [
    "LIBRARY_PREFIX",
    "NetworkError",
    "NotAStreamError",
    "Opened",
    "Service",
    "ServiceError",
    "StatusError",
    "UnreadableError",
    "clear_library_environment",
    "quiet_library_logging",
]
