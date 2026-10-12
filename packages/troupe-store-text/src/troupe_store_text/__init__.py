"""troupe's text event store: append-only JSON Lines segments git can merge (design D1, D3-D7).

Two ways in:

- ``open_store(theatre, vcs)``: the ``text`` store in the ``troupe.store`` entry point group,
  which is how troupe's event-store service opens it. troupe never imports this package.
- ``PERSISTENCE_MODULE=troupe_store_text``: an eventsourcing persistence module, with
  ``TROUPE_THEATRE`` (the theatre's directory) and ``TROUPE_VCS`` (the VCS adapter's name, ``files``
  when unset). The library's own recorder test suite runs against it this way.
"""

from pathlib import Path

from eventsourcing.persistence import InfrastructureFactory
from eventsourcing.utils import Environment, resolve_topic

from troupe.core.vcs import Vcs, load_vcs
from troupe_store_text.recorders import (
    TextAggregateRecorder,
    TextApplicationRecorder,
    TextProcessRecorder,
    TextSubscription,
    TextTrackingRecorder,
)
from troupe_store_text.store import Head, TextStore, shared_store

__all__ = [
    "Head",
    "TextAggregateRecorder",
    "TextApplicationRecorder",
    "TextFactory",
    "TextProcessRecorder",
    "TextStore",
    "TextSubscription",
    "TextTrackingRecorder",
    "open_store",
]


def open_store(theatre: Path, vcs: Vcs, *, purpose: str = "events") -> TextStore:
    """The theatre's text store, shared by everything in this process that opens it."""
    return shared_store(theatre, lambda: vcs, purpose)


class TextFactory(InfrastructureFactory[TextTrackingRecorder]):
    """Builds the text recorders for an eventsourcing application."""

    THEATRE = "TROUPE_THEATRE"
    VCS = "TROUPE_VCS"

    def __init__(self, env: Environment | dict[str, str] | None) -> None:
        super().__init__(env)
        theatre = self.env.get(self.THEATRE)
        if not theatre:
            msg = f"{self.THEATRE} must name the theatre's directory"
            raise OSError(msg)
        self.theatre = Path(theatre)
        self.vcs_name = self.env.get(self.VCS) or "files"

    def _store(self, purpose: str = "events") -> TextStore:
        return shared_store(self.theatre, lambda: load_vcs(self.vcs_name, self.theatre), purpose)

    def aggregate_recorder(self, purpose: str = "events") -> TextAggregateRecorder:
        return TextAggregateRecorder(self._store(purpose))

    def application_recorder(self) -> TextApplicationRecorder:
        return TextApplicationRecorder(self._store())

    def tracking_recorder(
        self, tracking_recorder_class: type[TextTrackingRecorder] | None = None
    ) -> TextTrackingRecorder:
        if tracking_recorder_class is None:
            topic = self.env.get(self.TRACKING_RECORDER_TOPIC)
            tracking_recorder_class = resolve_topic(topic) if topic else TextTrackingRecorder
        if not (
            isinstance(tracking_recorder_class, type)
            and issubclass(tracking_recorder_class, TextTrackingRecorder)
        ):
            msg = f"{tracking_recorder_class!r} isn't a text tracking recorder"
            raise TypeError(msg)
        return tracking_recorder_class(self._store())

    def process_recorder(self) -> TextProcessRecorder:
        return TextProcessRecorder(self._store())
