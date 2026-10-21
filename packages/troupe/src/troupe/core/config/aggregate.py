"""The config stream and its one event (spec: config; config-model design D2).

A theatre's config is one stream, with the same id in every theatre (a store holds one theatre).
Each command that changes config records exactly one ``Config.Changed``, holding every value it
changed and every config file it wrote or removed:

- ``changes``: one entry per value, ``{"path": [...keys], "before": "sha256:...", "after": value}``.
  ``before`` is the hash of the old value's canonical JSON, absent when it didn't exist; ``after``
  is the new value, absent when it was removed, and never an object.
- ``files``: ``{"path": "actors/tester.yaml", "hash": "sha256:..."}`` for each file written, with no
  hash for a file removed.

Config is never loaded with the library's ``load``: it's worked out from the stream's whole
history, both sides of any fork included (``troupe.core.config.merge``). So the aggregate class is
only the home of the event's topic, which is this class's import path: it isn't moved without
registering the old topic with the library.
"""

from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from eventsourcing.domain import Aggregate

from troupe.core.events.settling import Settled

STREAM: UUID = uuid5(NAMESPACE_URL, "https://troupe.run/streams/troupe.config")
"""The config stream's id, the same in every theatre."""


class Config(Aggregate):
    """A theatre's config, as a stream of changes."""

    @dataclass(frozen=True)
    class Changed(Aggregate.Event):
        """One command's change to config."""

        changes: list[dict[str, Any]]
        files: list[dict[str, Any]]

    class Settled(Settled):
        """Ends a fork in the config stream: its parents are every head, and its state is the
        merged config. Its own class, so its topic and its payload's schema are config's."""


CHANGED = "troupe.core.config.aggregate:Config.Changed"
SETTLED = "troupe.core.config.aggregate:Config.Settled"
TOPICS = (CHANGED, SETTLED)
"""Every topic config records: its changes, and the settling event its first write after a merge
records (config-model design D4)."""


def changed(
    version: int, changes: list[dict[str, Any]], files: list[dict[str, Any]]
) -> Config.Changed:
    """The ``Config.Changed`` event at ``version`` of the config stream."""
    return Config.Changed(
        originator_id=STREAM,
        originator_version=version,
        timestamp=Config.Changed.create_timestamp(),
        changes=changes,
        files=files,
    )
