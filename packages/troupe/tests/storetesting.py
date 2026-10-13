"""Helpers for the text event store's tests: theatres, events and snapshots of their files."""

import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from eventsourcing.domain import Aggregate
from eventsourcing.domain import event as aggregate_event
from eventsourcing.persistence import StoredEvent

from gitrepo import Repo
from troupe.core import strict_json
from troupe.core.events import EventStore
from troupe.core.vcs import Vcs, load_vcs
from troupe_store_text.store import TextStore
from troupe_vcs_git import GitAdapter


def event(stream: UUID | str, version: int, **payload: object) -> StoredEvent:
    """A stored event whose state is canonical JSON, as troupe's own events are."""
    state = strict_json.dumps({"timestamp": "t", **payload}).encode("utf-8")
    return StoredEvent(
        originator_id=stream, originator_version=version, topic="tests:E", state=state
    )


def fresh_store(theatre: Path, vcs: Vcs | None = None, **options: float) -> TextStore:
    """A store that reads the theatre's files from scratch, as a new process would."""
    return TextStore(theatre, vcs or load_vcs("files", theatre), **options)  # type: ignore[arg-type]


def snapshot(directory: Path) -> dict[str, str]:
    """Every file under ``directory``, with a hash of its bytes."""
    if not directory.exists():
        return {}
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def segments(theatre: Path) -> list[Path]:
    return sorted((theatre / ".troupe" / "events").glob("*.jsonl"))


def new_stream() -> UUID:
    return uuid4()


class Counter(Aggregate):
    """A small aggregate for tests: a value that can be set."""

    @aggregate_event("Created")
    def __init__(self, value: int = 0) -> None:
        self.value = value

    @aggregate_event("Set")
    def set(self, value: int) -> None:
        self.value = value


ADA = {"TROUPE_ACTOR": "human:ada@example.com"}


def files_service(
    theatre: Path, env: dict[str, str] | None = None, **options: object
) -> EventStore:
    """The event-store service over a theatre with no version control, acting as Ada."""
    vcs = load_vcs("files", theatre)
    return EventStore(theatre, vcs=vcs, recorder=TextStore(theatre, vcs), env=env or ADA, **options)  # type: ignore[arg-type]


def git_service(repo: Repo, env: dict[str, str] | None = None, **store: Any) -> EventStore:  # noqa: ANN401
    """The event-store service over a git theatre, with git isolated from this machine. ``store``
    passes options to the text store (poll_seconds, check_seconds, watcher)."""
    vcs = GitAdapter(repo.path, source=repo.env)
    recorder = TextStore(repo.path, vcs, **store)
    return EventStore(repo.path, vcs=vcs, recorder=recorder, env=env or ADA)
