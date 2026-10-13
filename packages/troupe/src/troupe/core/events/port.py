"""The event store port (spec: event-store; design D1; watch-event-segments design D0).

The text store in troupe-store-text implements it and is found by name through the ``troupe.store``
entry point group; troupe never imports it. Every write troupe makes goes through the service in
troupe.core.events, which checks lineage first.
"""

import importlib.metadata
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from eventsourcing.persistence import StoredEvent, Tracking

from troupe.core.errors import TroupeError
from troupe.core.notices import Notice
from troupe.core.vcs import Vcs

ENTRY_POINT_GROUP = "troupe.store"


class RecordedEvent(Protocol):
    """One recorded event, and where it is."""

    @property
    def id(self) -> str: ...
    @property
    def stream(self) -> UUID | str: ...
    @property
    def version(self) -> int: ...
    @property
    def topic(self) -> str: ...
    @property
    def parents(self) -> tuple[str, ...]: ...
    @property
    def state(self) -> bytes: ...
    @property
    def path(self) -> Path: ...
    @property
    def line(self) -> int: ...
    @property
    def lineage(self) -> dict[str, Any] | None: ...


class Head(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def version(self) -> int: ...


class EventRecorder(Protocol):
    """What the service needs from a store, beyond the library's recorder contract."""

    def insert(
        self,
        stored_events: Sequence[StoredEvent],
        *,
        tracking: Tracking | None = None,
        settling_parents: Sequence[str] | None = None,
    ) -> list[int]: ...

    def select(
        self,
        stream: UUID | str,
        *,
        gt: int | None = None,
        lte: int | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> Sequence[RecordedEvent]: ...

    def heads(self, stream: UUID | str) -> Sequence[Head]: ...
    def forks(self) -> list[UUID | str]: ...
    def history(self, stream: UUID | str) -> Sequence[RecordedEvent]: ...
    def recordings(self, event: str) -> Sequence[RecordedEvent]: ...
    def event(self, event: str) -> RecordedEvent | None: ...
    def notifications(
        self, low: int, limit: int, stop: int | None, topics: Sequence[str]
    ) -> Sequence[tuple[int, RecordedEvent]]: ...
    def max_notification_id(self) -> int | None: ...
    def notices(self) -> list[Notice]: ...

    def listen(self, event: threading.Event) -> None:
        """Set ``event`` whenever a new event is recorded, whoever wrote it, within a bound and
        without the caller looking on a timer. A store that can only poll says so in its notices
        (``events.subscription-polling``) for as long as it does (watch-event-segments D0)."""
        ...

    def unlisten(self, event: threading.Event) -> None:
        """Stop setting ``event``."""
        ...


def installed_stores() -> dict[str, importlib.metadata.EntryPoint]:
    return {ep.name: ep for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)}


def load_store(name: str, theatre: str | os.PathLike[str], vcs: Vcs) -> EventRecorder:
    """The event store registered as ``name``, for the theatre at ``theatre``."""
    stores = installed_stores()
    if name not in stores:
        installed = ", ".join(sorted(stores)) or "none"
        raise TroupeError(
            "events.unknown-store",
            problem=f"No event store named {name!r} is installed (installed: {installed}).",
            fix="Use one of the installed stores, or install the package that provides this one.",
            details={"store": name, "installed": sorted(stores)},
        )
    opener = stores[name].load()
    store: EventRecorder = opener(Path(theatre), vcs)
    return store
