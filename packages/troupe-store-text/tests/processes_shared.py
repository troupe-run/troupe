"""What test_processes.py and test_processes_unit.py share."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from troupe.core.vcs import load_vcs
from troupe.platform import watching
from troupe_store_text.store import TextStore


def outcome(stdout: str) -> str:
    """A child's outcome: its last line. Every earlier line must be a lock-wait announcement,
    which the spec requires of a writer that waits ("Writers wait for each other, bounded and
    announced")."""
    *announcements, last = stdout.strip().splitlines()
    for line in announcements:
        assert line.startswith("waiting "), f"unexpected output before the outcome: {line!r}"
    return last


@contextmanager
def listened(store: TextStore) -> Iterator[threading.Event]:
    heard = threading.Event()
    store.listen(heard)
    try:
        yield heard
    finally:
        store.unlisten(heard)


def store_for(theatre: Path, **options: object) -> TextStore:
    return TextStore(theatre, load_vcs("files", theatre), **options)  # type: ignore[arg-type]


class Manual(watching._Backend):
    """A watch that reports a change only when the test says so."""

    def __init__(self) -> None:
        self.reported = threading.Event()
        self._stopped = False

    def wait(self, timeout: float | None) -> bool:
        changed = self.reported.wait(timeout)
        self.reported.clear()
        return changed and not self._stopped

    def interrupt(self) -> None:
        self._stopped = True
        self.reported.set()

    def release(self) -> None:
        pass
