"""What one request through the service seam gives back: a response being read, or one of a closed
set of failures (anthropic-runner design D1). Plain types, so the loop and the exchange don't import
the anthropic package; service.py, which does, makes them.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Opened:
    """A response whose status was 2xx and whose stream is being read."""

    status: int
    headers: dict[str, str]
    """By lower-case name."""
    events: Iterator[dict[str, Any]]
    """Each stream event as the library parsed it."""


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


__all__ = [
    "NetworkError",
    "NotAStreamError",
    "Opened",
    "ServiceError",
    "StatusError",
    "UnreadableError",
]
