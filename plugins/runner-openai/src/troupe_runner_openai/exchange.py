"""One exchange with the service: a request, its retries, and the reply (openai-style-runner design
D8, D10; transcript-record-kinds design D5).

``exchange`` sends a request, reads its streamed response into a reply, and retries what retrying
can fix: a rate limit (429), a server error (5xx), a network error, a timeout and a stream cut
short. Each retry is reported through ``on_retry`` before its delay. What retrying can't fix (a
refused credential, quota, a context-length error, any other client error, a redirect, a wait
longer than the cap, a response the service finished in a shape that can't be read, a 2xx that
isn't a stream, or attempts running out) raises ExchangeFailedError, with the message the run's
result carries.

Every request body, response status and kept header, stream line, error body and dropped stream
is passed to ``record`` with its kind, for the transcript (transcript-record-kinds design D5): a
request body is ``sent``, a stream line or error body ``received``, each as the bytes themselves,
and a response's status with its kept headers, or a dropped stream, a ``note`` of the runner's own,
compact JSON. Masking the credential is the runner's: it masks everything it sends.
"""

import email.utils
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from troupe_plugin_sdk import runner as p
from troupe_runner_openai.defaults import (
    MAX_ATTEMPTS,
    RETRY_BASE_DELAY_SECONDS,
    RETRY_MAX_DELAY_SECONDS,
    SERVICE_FAILURE_CODES,
    SUMMARY_MAX_BYTES,
    TRANSCRIPT_HEADER_PREFIXES,
    TRANSCRIPT_HEADERS,
)
from troupe_runner_openai.service import (
    AbortedError,
    Call,
    Endpoint,
    NetworkError,
    Response,
    StatusError,
)
from troupe_runner_openai.stream import Reply, ShapeError, StreamError, StreamParser

RetryReason = Literal["rate-limit", "server", "network"]


class ExchangeFailedError(Exception):
    """The exchange failed in a way retrying can't fix. ``message`` is the result's message.

    ``answered`` is true when the service finished a response the run must count, one in the wrong
    shape (openai-wrong-shape-ends-run design D5), and ``usage`` is its usage when that could be
    read. Every other failure got no response to count."""

    def __init__(
        self, message: str, answered: bool = False, usage: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.answered = answered
        self.usage = usage


@dataclass(frozen=True)
class Retry:
    """A retry about to happen: the attempt that failed, the delay before the next, and why."""

    attempt: int
    max_attempts: int
    delay_seconds: float
    reason: RetryReason
    message: str


@dataclass(frozen=True)
class _Retryable:
    reason: RetryReason
    message: str
    wait: float | None = None
    """The delay the service asked for, in seconds, or None when it didn't ask."""


Record = Callable[[p.TranscriptKind, bytes], None]
"""Takes each transcript record: its kind and its bytes."""
Wait = Callable[[float], bool]
"""Wait up to the given seconds; true if the wait was cut short because the run is stopping."""


def _cut(text: str, limit: int = SUMMARY_MAX_BYTES) -> str:
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", "ignore") + f"… ({len(data) - limit} bytes left out)"


def _sentence(text: str) -> str:
    """``text`` ending as a sentence, so another can follow it."""
    return text if text.endswith((".", "!", "?", ")", "]")) else f"{text}."


def _service_error(body: bytes) -> tuple[str, str | None]:
    """The service's own message and error code, from a body in OpenAI's shape, or the body as
    text when it isn't that shape."""
    text = body.decode("utf-8", "replace").strip()
    try:
        data = json.loads(text)
    except ValueError:
        return _cut(text) or "(no message)", None
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        codes = [error.get("code"), error.get("type")]
        code = next((c for c in codes if isinstance(c, str) and c), None)
        return _cut(message) if isinstance(message, str) and message else _cut(text), code
    if isinstance(error, str):
        return _cut(error), None
    return _cut(text) or "(no message)", None


def retry_after(value: str | None, now: float | None = None) -> float | None:
    """A Retry-After header's delay in seconds, from seconds or an HTTP date, or None when there's
    none or it can't be read."""
    if value is None:
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        seconds = when.timestamp() - (time.time() if now is None else now)
    if not math.isfinite(seconds):
        return None
    return max(0.0, seconds)


def classify(error: StatusError, url: str = "") -> _Retryable:
    """A status the exchange may retry, as a _Retryable. Raises ExchangeFailedError for one it
    mustn't."""
    status = error.status
    message, code = _service_error(error.body)
    said = f"HTTP {status}: {message}"
    told = _sentence(message)  # ending as a sentence, so a fix can follow it
    if 300 <= status < 400:
        location = error.headers.get("location", "(no Location)")
        raise ExchangeFailedError(
            f"The service redirected the request (HTTP {status}) to {location}. troupe never "
            "follows a redirect, so the credential and the conversation go only where the "
            "runtime names: point the runtime's endpoint at the service itself."
        )
    if status in (401, 403):
        raise ExchangeFailedError(
            f"The service refused the credential (HTTP {status}): {told} Check the key the "
            "actor's runtime names, and that it's allowed to use this model."
        )
    if status == 429 and code == "insufficient_quota":
        raise ExchangeFailedError(f"The account is out of quota (HTTP 429): {message}")
    if status == 429:
        return _Retryable("rate-limit", said, retry_after(error.headers.get("retry-after")))
    if status == 400 and code == "context_length_exceeded":
        raise ExchangeFailedError(
            f"The conversation is longer than the model's context (HTTP 400): {told} Give the "
            "actor a smaller task, or a runtime whose model has a longer context."
        )
    if status == 404 and code is None:
        raise ExchangeFailedError(
            f"Nothing answered at {url or 'the endpoint'} (HTTP 404): {told} The runtime's "
            "endpoint must be the base URL its Responses API is served under, often ending "
            "in /v1, such as http://127.0.0.1:11434/v1 for Ollama."
        )
    if status >= 500:
        return _Retryable("server", said, retry_after(error.headers.get("retry-after")))
    raise ExchangeFailedError(f"The service refused the request (HTTP {status}): {message}")


def _failed(reply: Reply) -> _Retryable:
    """A failed response or error event the exchange may retry, as a _Retryable: only when its code
    is the service's own failure (design D8). Raises ExchangeFailedError for any other."""
    failure = reply.failure
    code = None if failure is None else failure.code
    message = "(no message)" if failure is None else failure.message.rstrip(".")
    said = f"{code or 'no code'}: {message}"
    if code in SERVICE_FAILURE_CODES:
        return _Retryable("server", f"The service failed the response ({said})")
    raise ExchangeFailedError(f"The service failed the response ({said}).")


def _kept(headers: dict[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in sorted(headers.items())
        if name in TRANSCRIPT_HEADERS or name.startswith(TRANSCRIPT_HEADER_PREFIXES)
    }


STREAM_TYPE = "text/event-stream"
"""The media type a streamed response is sent as, which the runner asks for (design D4)."""


def _not_a_stream(response: Response, record: Record) -> ExchangeFailedError | None:
    """The failure for a 2xx whose Content-Type is present and isn't a stream, with its body
    recorded; None for a stream, or a response that names no type and is read as one (design D4)."""
    said = response.headers.get("content-type")
    if said is None or said.partition(";")[0].strip().lower() == STREAM_TYPE:
        return None
    try:
        body = response.body()
    except NetworkError as error:
        told = f"its body couldn't be read ({str(error).rstrip('.')})."
    else:
        record("received", body)
        told = _sentence(_service_error(body)[0])
    return ExchangeFailedError(
        f"The service answered HTTP {response.status} with {_cut(said.strip(), 200)}, not the "
        f"stream ({STREAM_TYPE}) the runner asked for: {told} Check that the runtime's endpoint "
        "serves OpenAI's Responses API with streaming."
    )


def _note(record: Record, note: dict[str, Any]) -> None:
    record("note", json.dumps(note, ensure_ascii=False, separators=(",", ":")).encode())


def _attempt(call: Call, record: Record) -> Reply:
    try:
        response = call.open()
    except StatusError as error:
        _note(record, {"status": error.status, "headers": _kept(error.headers)})
        record("received", error.body)
        raise
    _note(record, {"status": response.status, "headers": _kept(response.headers)})
    parser = StreamParser()
    try:
        failure = _not_a_stream(response, record)
        if failure is not None:
            raise failure
        for line in response.lines():
            record("received", line.encode())
            if parser.feed(line):
                break
        return parser.reply()
    finally:
        response.close()


def exchange(
    endpoint: Endpoint,
    body: bytes,
    credential: str | None,
    on_retry: Callable[[Retry], None],
    record: Record,
    wait: Wait,
    make_call: Callable[[Endpoint, bytes, str | None], Call] = Call,
    on_call: Callable[[Call | None], None] = lambda _: None,
    max_attempts: int = MAX_ATTEMPTS,
    base_delay: float = RETRY_BASE_DELAY_SECONDS,
    max_delay: float = RETRY_MAX_DELAY_SECONDS,
) -> Reply:
    """Send ``body`` and return the reply, retrying as the module docstring says. ``on_call`` is
    given each call as it starts, and None when it's over, so another thread can abort it. Raises
    ExchangeFailedError, or AbortedError when the run is stopping."""
    record("sent", body)
    for attempt in range(1, max_attempts + 1):
        call = make_call(endpoint, body, credential)
        on_call(call)
        try:
            reply = _attempt(call, record)
            if reply.failure is None or reply.status not in ("failed", "error"):
                return reply
            retryable = _failed(reply)
        except StatusError as error:
            retryable = classify(error, endpoint.responses_url)
        except ShapeError as error:
            raise ExchangeFailedError(
                f"The service's response can't be read: {_sentence(str(error))} Retrying can't "
                "fix a response the service finished, so the run ends here. Check that the "
                "runtime's endpoint serves OpenAI's Responses API.",
                answered=True,
                usage=error.usage,
            ) from None
        except (NetworkError, StreamError) as error:
            retryable = _Retryable("network", str(error))
            _note(record, {"dropped": retryable.message})
        finally:
            on_call(None)
        if attempt == max_attempts:
            raise ExchangeFailedError(
                f"{_sentence(retryable.message)} Gave up after {max_attempts} attempts."
            )
        delay = min(base_delay * 2 ** (attempt - 1), max_delay)
        asked = retryable.wait
        if asked is not None and asked > max_delay and retryable.reason == "rate-limit":
            raise ExchangeFailedError(
                f"The service asked to wait {asked:g} seconds before retrying "
                f"({retryable.message}), longer than the runner waits ({max_delay:g} seconds)."
            )
        if asked is not None:
            # A server error's wait is capped rather than fatal: the cap is a rate limit's (D8).
            delay = min(asked, max_delay)
        on_retry(Retry(attempt, max_attempts, delay, retryable.reason, retryable.message))
        if wait(delay):
            raise AbortedError
    raise AssertionError("unreachable: the last attempt returns or raises")  # pragma: no cover


__all__ = ["ExchangeFailedError", "Retry", "RetryReason", "classify", "exchange", "retry_after"]
