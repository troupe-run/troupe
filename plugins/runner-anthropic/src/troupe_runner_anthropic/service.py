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
from collections.abc import Iterator, Mapping
from typing import Any, Final

import anthropic
import httpx2

from troupe_runner_anthropic.defaults import (
    CONNECT_TIMEOUT_SECONDS,
    STREAM_TIMEOUT_SECONDS,
    WRITE_TIMEOUT_SECONDS,
)
from troupe_runner_anthropic.failures import (
    NetworkError,
    NotAStreamError,
    Opened,
    ServiceError,
    StatusError,
    UnreadableError,
)
from troupe_runner_anthropic.library import (
    LIBRARY_LOGGERS,
    LIBRARY_PREFIX,
    Writable,
    clear_library_environment,
    quiet_library_logging,
)
from troupe_runner_anthropic.runtime import Runtime

STREAM_TYPE: Final = "text/event-stream"
"""The media type a streamed reply is sent as, which the runner asks for."""


# Failures are in failures.py, and the library's environment and logging in library.py: neither
# imports the library.


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
    "LIBRARY_LOGGERS",
    "LIBRARY_PREFIX",
    "NetworkError",
    "NotAStreamError",
    "Opened",
    "Service",
    "ServiceError",
    "StatusError",
    "UnreadableError",
    "Writable",
    "clear_library_environment",
    "quiet_library_logging",
]
