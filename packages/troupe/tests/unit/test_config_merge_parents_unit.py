"""Config's merge refuses an event whose parent isn't here, naming it as the protocol's details for
``events.missing-parent`` require (spec: event-store, "A missing parent is refused"; #506).

The store's ``history()`` refuses nothing, so config's merge is what checks the parents of the
config stream (config-model design D5). The history is built in memory: the check runs before any
event's payload is read."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from troupe.core.config import aggregate
from troupe.core.config.merge import merge
from troupe.core.errors import TroupeError

FIRST = "sha256:" + "1" * 64
SECOND = "sha256:" + "2" * 64
THIRD = "sha256:" + "3" * 64
GONE = "sha256:" + "0" * 64


@dataclass(frozen=True)
class Record:
    """A recorded event, as the store returns it."""

    id: str
    parents: tuple[str, ...]
    path: Path
    line: int
    topic: str = aggregate.CHANGED
    state: bytes = b'{"changes": []}'
    version: int = 1
    stream: str = str(aggregate.STREAM)
    lineage: dict[str, Any] | None = None


def test_an_event_whose_parent_isnt_here_is_refused_naming_it_and_its_line() -> None:
    history = [
        Record(FIRST, (), Path("a.jsonl"), 1),
        Record(SECOND, (FIRST,), Path("a.jsonl"), 2),
        Record(THIRD, (SECOND, GONE), Path("b.jsonl"), 3),
    ]
    with pytest.raises(TroupeError) as caught:
        merge(history)
    error = caught.value
    assert error.code == "events.missing-parent"
    assert error.path == "b.jsonl"
    assert error.details == {"line": 3, "event": THIRD, "missingParent": GONE, "onlyIn": []}
    assert error.problem == f"Line 3 of an event segment follows event {GONE}, which isn't here."
    assert "Restore the file" in error.fix
    assert "remove this file too" in error.fix


def test_the_first_event_with_a_missing_parent_is_the_one_named() -> None:
    history = [
        Record(FIRST, (GONE,), Path("a.jsonl"), 4),
        Record(SECOND, (THIRD,), Path("b.jsonl"), 5),
    ]
    with pytest.raises(TroupeError) as caught:
        merge(history)
    assert caught.value.details["event"] == FIRST
    assert caught.value.details["line"] == 4
