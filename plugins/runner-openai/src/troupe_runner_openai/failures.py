"""What one request through the service seam gives back: a response being read, or one of a closed
set of failures (openai-library design D1, D4). Plain types, so the loop and the exchange don't
import the openai package; service.py, which does, makes them.
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
    events: Iterator[Any]
    """Each stream event as the library parsed it: a dict, or the JSON value an event's data was
    when that isn't an object."""


class ServiceError(Exception):
    """A request that failed: one of the closed set below."""


class StatusError(ServiceError):
    """The service answered with a status other than 2xx, redirects included."""

    def __init__(self, status: int, headers: Mapping[str, str], body: bytes) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.headers = {name.lower(): value for name, value in headers.items()}
        """By lower-case name."""
        self.body = body


class NotAStreamError(ServiceError):
    """A 2xx whose Content-Type is present and isn't a stream. ``body`` is what could be read of
    it, and ``broke`` says why the rest couldn't be, when it couldn't."""

    def __init__(
        self,
        status: int,
        headers: Mapping[str, str],
        content_type: str,
        body: bytes,
        broke: str | None,
    ) -> None:
        super().__init__(f"HTTP {status} {content_type}")
        self.status = status
        self.headers = {name.lower(): value for name, value in headers.items()}
        """By lower-case name."""
        self.content_type = content_type
        self.body = body
        self.broke = broke


class NetworkError(ServiceError):
    """No whole answer: the connection failed, broke, went quiet past a timeout, sent a line past
    the runner's cap or bytes that aren't UTF-8. The message says which."""


class UnreadableError(ServiceError):
    """The service finished an event the library can't read: its data isn't JSON."""


__all__ = [
    "NetworkError",
    "NotAStreamError",
    "Opened",
    "ServiceError",
    "StatusError",
    "UnreadableError",
]
