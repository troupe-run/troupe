"""One exchange with the service: a request, its retries, and the reply (anthropic-runner design D7,
D8, D10, D11).

``exchange`` sends a request through the service seam, reads its stream into a reply, and retries
what retrying can fix: a rate limit (429), a server error (5xx, ``overloaded_error`` included, in a
status or in the stream's ``error`` event), a network error, a timeout and a stream cut short. The
library's own retries are off, so these are the only ones. Each retry is reported through
``on_retry`` before its delay. What retrying can't fix raises ExchangeFailedError with the result's
message and reason, from the one table in ``classify``. A failure the context table names
(context.py) is never retried.

Every request's parameters, response status and kept headers, stream event, error body and dropped
stream is passed to ``record`` with its kind, for the transcript: the parameters ``sent``, each
event and error body ``received``, as the library gives them, serialised, and a status or a dropped
stream a ``note`` of the runner's own. Masking the credential is the runner's: it masks everything
it sends.
"""

import email.utils
import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from troupe_plugin_sdk import runner as p
from troupe_plugin_sdk.runner import FailureReason
from troupe_runner_anthropic.context import signal_of
from troupe_runner_anthropic.defaults import (
    MAX_ATTEMPTS,
    RETRY_BASE_DELAY_SECONDS,
    RETRY_MAX_DELAY_SECONDS,
    SUMMARY_MAX_BYTES,
    TRANSCRIPT_HEADER_PREFIXES,
    TRANSCRIPT_HEADERS,
)
from troupe_runner_anthropic.reply import Reply, ReplyParser, ShapeError
from troupe_runner_anthropic.service import (
    NetworkError,
    NotAStreamError,
    Opened,
    StatusError,
    UnreadableError,
)

RetryReason = Literal["rate-limit", "server", "network"]

SERVER_ERROR_TYPES: tuple[str, ...] = ("api_error", "overloaded_error")
"""The Messages API's error types that are the service's own failure, retried as server failures
when they come in a stream's ``error`` event, whose status is the stream's 200."""


class ExchangeFailedError(Exception):
    """The exchange failed in a way retrying can't fix. ``message`` is the result's message, and
    ``reason`` its reason. ``context`` is true for a context-length refusal, which a run told to
    compact may answer by compacting. ``usage`` is a finished reply's usage when one in the wrong
    shape ended it (it counts toward the run's)."""

    def __init__(
        self,
        message: str,
        reason: FailureReason,
        context: bool = False,
        usage: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.reason: FailureReason = reason
        self.context = context
        self.usage = usage


class StoppedError(Exception):
    """The run is stopping: the exchange sent nothing more."""


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
Open = Callable[[Mapping[str, Any]], Opened]
"""Sends one request through the service seam (Service.stream)."""


def _cut(text: str, limit: int = SUMMARY_MAX_BYTES) -> str:
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", "ignore") + f"… ({len(data) - limit} bytes left out)"


def _sentence(text: str) -> str:
    """``text`` ending as a sentence, so another can follow it."""
    return text if text.endswith((".", "!", "?", ")", "]")) else f"{text}."


def retry_after(headers: Mapping[str, str], now: float | None = None) -> float | None:
    """The delay a response asked for, in seconds: ``retry-after-ms``, else ``Retry-After`` as
    seconds or an HTTP date; None when there's none or it can't be read."""
    millis = headers.get("retry-after-ms")
    if millis is not None:
        try:
            seconds = float(millis) / 1000
        except ValueError:
            seconds = math.nan
        if math.isfinite(seconds):
            return max(0.0, seconds)
    value = headers.get("retry-after")
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


def _message(failure: StatusError) -> str:
    if failure.message:
        return _cut(failure.message)
    text = failure.body.decode("utf-8", "replace").strip()
    return _cut(text) if text else "(no message)"


def classify(failure: StatusError, url: str = "") -> _Retryable:
    """A status the exchange may retry, as a _Retryable. Raises ExchangeFailedError for one it
    mustn't, with its reason from this one table (spec: anthropic-runner, "Failures retrying can't
    fix end the run at once")."""
    status, kind = failure.status, failure.error_type
    message = _message(failure)
    named = (
        f"an error event in the reply's stream{f', {kind}' if kind else ''}"
        if failure.in_stream
        else f"HTTP {status}{f' {kind}' if kind else ''}"
    )
    said = f"{named}: {message}"
    told = _sentence(message)
    signal = signal_of(status, kind, failure.message or message)
    if signal is not None:
        raise ExchangeFailedError(
            f"The conversation is longer than the model's context ({signal.engine}, {named}): "
            f"{told} Give the actor a smaller task, or a model with a longer context.",
            "context-length",
            context=True,
        )
    if 300 <= status < 400:
        location = failure.headers.get("location", "(no Location)")
        raise ExchangeFailedError(
            f"The service redirected the request (HTTP {status}) to {location}. troupe never "
            "follows a redirect, so the credential and the conversation go only where the "
            "runtime names: point the runtime's endpoint at the service itself.",
            "configuration",
        )
    if status in (401, 403) or kind in ("authentication_error", "permission_error"):
        raise ExchangeFailedError(
            f"The service refused the credential ({named}): {told} Check the key the actor's "
            "runtime names, and that it's allowed to use this model.",
            "authentication",
        )
    if status == 402 or kind == "billing_error":
        raise ExchangeFailedError(
            f"The account can't pay for the request ({named}): {message}", "quota"
        )
    if status == 429 or kind == "rate_limit_error":
        return _Retryable("rate-limit", said, retry_after(failure.headers))
    if status == 404 and kind is None:
        raise ExchangeFailedError(
            f"Nothing answered at {url or 'the endpoint'} (HTTP 404): {told} The runtime's "
            "endpoint must be the Messages API's base URL, below which the library adds "
            "/v1/messages, such as https://api.anthropic.com or http://127.0.0.1:1234.",
            "configuration",
        )
    if status == 404:
        raise ExchangeFailedError(
            f"The service has no such model, or no such API ({named}): {told} Check the model "
            "the actor or its runtime names.",
            "configuration",
        )
    if status >= 500 or (failure.in_stream and kind in SERVER_ERROR_TYPES):
        return _Retryable("server", said, retry_after(failure.headers))
    raise ExchangeFailedError(f"The service refused the request ({said})", "other")


def _kept(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in sorted(headers.items())
        if name in TRANSCRIPT_HEADERS or name.startswith(TRANSCRIPT_HEADER_PREFIXES)
    }


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _note(record: Record, note: dict[str, Any]) -> None:
    record("note", _json(note))


def _attempt(open_: Open, params: Mapping[str, Any], record: Record) -> Reply:
    try:
        opened = open_(params)
    except StatusError as failure:
        _note(record, {"status": failure.status, "headers": _kept(failure.headers)})
        record("received", failure.body)
        raise
    except NotAStreamError as failure:
        _note(record, {"status": failure.status, "headers": {"content-type": failure.content_type}})
        record("received", failure.body)
        raise
    _note(record, {"status": opened.status, "headers": _kept(opened.headers)})
    parser = ReplyParser()
    try:
        for event in opened.events:
            record("received", _json(event))
            if parser.feed(event):
                return parser.reply()
    except StatusError as failure:  # an error event in the stream
        record("received", failure.body)
        raise
    raise NetworkError("the reply's stream ended before message_stop")


def exchange(
    open_: Open,
    params: Mapping[str, Any],
    url: str,
    on_retry: Callable[[Retry], None],
    record: Record,
    wait: Wait,
    begin: Callable[[], bool] = lambda: True,
    end: Callable[[], None] = lambda: None,
    max_attempts: int = MAX_ATTEMPTS,
    base_delay: float = RETRY_BASE_DELAY_SECONDS,
    max_delay: float = RETRY_MAX_DELAY_SECONDS,
) -> Reply:
    """Send ``params`` and return the reply, retrying as the module docstring says. ``begin`` is
    called before each attempt and returns False when the run is stopping (so nothing is sent);
    ``end`` after it. Raises ExchangeFailedError, or StoppedError when the run is stopping."""
    record("sent", _json(dict(params)))
    for attempt in range(1, max_attempts + 1):
        if not begin():
            raise StoppedError
        try:
            return _attempt(open_, params, record)
        except StatusError as failure:
            retryable = classify(failure, url)
        except NotAStreamError as failure:
            raise ExchangeFailedError(
                f"The service answered HTTP {failure.status} with "
                f"{_cut(failure.content_type.strip(), 200)}, not the stream (text/event-stream) "
                "the runner asked for. Check that the runtime's endpoint serves the Anthropic "
                "Messages API with streaming.",
                "configuration",
            ) from None
        except (ShapeError, UnreadableError) as error:
            raise ExchangeFailedError(
                f"The service's reply can't be read: {_sentence(str(error))} Retrying can't fix a "
                "reply the service finished, so the run ends here. Check that the runtime's "
                "endpoint serves the Anthropic Messages API.",
                "engine",
                usage=error.usage if isinstance(error, ShapeError) else None,
            ) from None
        except NetworkError as error:
            retryable = _Retryable("network", str(error))
            _note(record, {"dropped": retryable.message})
        finally:
            end()
        if attempt == max_attempts:
            # The run ends with its last retry's reason (spec: runner-protocol).
            raise ExchangeFailedError(
                f"{_sentence(retryable.message)} Gave up after {max_attempts} attempts.",
                retryable.reason,
            )
        delay = min(base_delay * 2 ** (attempt - 1), max_delay)
        asked = retryable.wait
        if asked is not None and asked > max_delay and retryable.reason == "rate-limit":
            raise ExchangeFailedError(
                f"The service asked to wait {asked:g} seconds before retrying "
                f"({retryable.message}), longer than the runner waits ({max_delay:g} seconds).",
                "rate-limit",
            )
        if asked is not None:
            # A server error's wait is cut to the cap rather than fatal.
            delay = min(asked, max_delay)
        on_retry(Retry(attempt, max_attempts, delay, retryable.reason, retryable.message))
        if wait(delay):
            raise StoppedError
    raise AssertionError("unreachable: the last attempt returns or raises")  # pragma: no cover


__all__ = [
    "SERVER_ERROR_TYPES",
    "ExchangeFailedError",
    "Record",
    "Retry",
    "RetryReason",
    "StoppedError",
    "Wait",
    "classify",
    "exchange",
    "retry_after",
]
