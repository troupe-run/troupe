"""The eventsourcing recorders, as views of one TextStore (spec: event-store; design D5, D10).

The library's integrity error passes through unchanged, because its optimistic concurrency depends
on it. Everything else troupe adds (forks, settling, history, notices) is on TextStore.
"""

from collections.abc import Sequence
from threading import Event
from typing import Any
from uuid import UUID

from eventsourcing.persistence import (
    AggregateRecorder,
    ApplicationRecorder,
    ListenNotifySubscription,
    Notification,
    ProcessRecorder,
    StoredEvent,
    Tracking,
    TrackingRecorder,
)

from troupe_store_text.store import TextStore


class TextAggregateRecorder(AggregateRecorder):
    """Events by stream."""

    def __init__(self, store: TextStore) -> None:
        self.store = store

    def insert_events(
        self,
        stored_events: Sequence[StoredEvent],
        **kwargs: Any,  # noqa: ANN401 - the library's signature
    ) -> Sequence[int] | None:
        if not stored_events:
            return None
        self.store.insert(stored_events)
        return None

    def select_events(
        self,
        originator_id: UUID | str,
        *,
        gt: int | None = None,
        lte: int | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> Sequence[StoredEvent]:
        return [
            StoredEvent(
                originator_id=r.stream,
                originator_version=r.version,
                topic=r.topic,
                state=r.state,
            )
            for r in self.store.select(originator_id, gt=gt, lte=lte, desc=desc, limit=limit)
        ]


class TextApplicationRecorder(TextAggregateRecorder, ApplicationRecorder):
    """Events by stream, and in this branch's notification order."""

    def insert_events(
        self,
        stored_events: Sequence[StoredEvent],
        **kwargs: Any,  # noqa: ANN401 - the library's signature
    ) -> Sequence[int] | None:
        return self.store.insert(stored_events, tracking=kwargs.get("tracking"))

    def select_notifications(
        self,
        start: int | None,
        limit: int,
        stop: int | None = None,
        topics: Sequence[str] = (),
        *,
        inclusive_of_start: bool = True,
    ) -> Sequence[Notification]:
        low = 1 if start is None else start if inclusive_of_start else start + 1
        return [
            Notification(
                id=n,
                originator_id=r.stream,
                originator_version=r.version,
                topic=r.topic,
                state=r.state,
            )
            for n, r in self.store.notifications(low, limit, stop, topics)
        ]

    def max_notification_id(self) -> int | None:
        return self.store.max_notification_id()

    def subscribe(self, gt: int | None = None, topics: Sequence[str] = ()) -> "TextSubscription":
        return TextSubscription(self, gt=gt, topics=topics)

    def listen(self, event: Event) -> None:
        self.store.listen(event)

    def unlisten(self, event: Event) -> None:
        self.store.unlisten(event)


class TextSubscription(ListenNotifySubscription[TextApplicationRecorder]):
    """The library's own subscription; the recorder owes only listen and unlisten (design D10)."""

    def __init__(
        self,
        recorder: TextApplicationRecorder,
        gt: int | None = None,
        topics: Sequence[str] = (),
    ) -> None:
        super().__init__(recorder=recorder, gt=gt, topics=topics)
        self._recorder.listen(self._has_been_notified)

    def stop(self) -> None:
        super().stop()
        self._recorder.unlisten(self._has_been_notified)


class TextTrackingRecorder(TrackingRecorder):
    """Followers' positions, local and per branch (design D5)."""

    def __init__(self, store: TextStore) -> None:
        self.store = store

    def insert_tracking(self, tracking: Tracking) -> None:
        self.store.insert_tracking(tracking)

    def max_tracking_id(self, application_name: str) -> int | None:
        return self.store.max_tracking_id(application_name)


class TextProcessRecorder(TextTrackingRecorder, TextApplicationRecorder, ProcessRecorder):
    """Events and followers' positions together: both are checked before either is written."""

    def __init__(self, store: TextStore) -> None:
        self.store = store
