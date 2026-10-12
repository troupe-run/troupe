"""The session a surface calls the core in (spec: client-protocol; perform-status-logs design D2).

The session is never part of a message. It holds what the surface establishes for itself: the
theatre (the CLI finds it from the working directory; a run server addresses it by id), the
environment the identity chain and the policy seam read, the clock, and a way to cancel a
long-running call. So no request can name a host path, claim an identity or loosen a policy.
"""

import asyncio
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class CancelSignal:
    """A request to cancel a long-running call, safe to make from any thread or a signal handler.

    The core binds it to its event loop while a call runs, so a request made from a Ctrl-C handler
    reaches the run host through the loop rather than touching it from outside.
    """

    def __init__(self) -> None:
        self._requested = threading.Event()
        self._lock = threading.Lock()
        self._bound: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []

    def request(self) -> None:
        """Ask for the call to be cancelled. Repeating it changes nothing."""
        self._requested.set()
        with self._lock:
            bound = list(self._bound)
        for loop, event in bound:
            loop.call_soon_threadsafe(event.set)

    @property
    def requested(self) -> bool:
        return self._requested.is_set()

    def bind(self) -> asyncio.Event:
        """An asyncio event on the running loop, set when cancel is requested (at once if it
        already was)."""
        event = asyncio.Event()
        with self._lock:
            self._bound.append((asyncio.get_running_loop(), event))
        if self._requested.is_set():
            event.set()
        return event


@dataclass(frozen=True)
class Session:
    """What a surface establishes before calling the core."""

    theatre: Path
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    clock: Clock = utc_now
    cancel: CancelSignal = field(default_factory=CancelSignal)
