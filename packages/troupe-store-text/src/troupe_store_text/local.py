"""The local, gitignored files: the notification order and followers' positions (design D5).

Both live under ``.troupe/local/`` and belong to this clone alone, per branch:

- ``order/<branch-key>.jsonl``: ``{"epoch": ...}``, then ``{"n": 1, "event": "<id>"}``,
  ``{"n": 2, ...}`` and so on. Notification ids are dense from 1, only ever appended, never
  renumbered. A new epoch means the order was rebuilt.
- ``tracking/<branch-key>.jsonl``: ``{"epoch", "application_name", "notification_id"}`` lines. A
  position recorded under an earlier epoch no longer counts, so a follower starts again after a
  rebuild.

Reading is strict. A torn last line (an append that was interrupted) is trimmed, because troupe
alone writes these files and that line never took effect; damage anywhere else is an error naming
the file and the line.
"""

import hashlib
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from troupe.core import strict_json
from troupe.core.errors import TroupeError
from troupe.core.files import replace_file
from troupe.platform.files import append_bytes


def branch_key(adapter: str, branch: str | None) -> str:
    """A filename for a branch's local files: readable, safe on every platform, and unique, so
    ``a/b`` and ``a-b`` never share one (design D2)."""
    if branch is None:
        return "default" if adapter == "files" else "detached"
    readable = re.sub(r"[^A-Za-z0-9._-]", "-", branch)[:60].strip(".")
    return f"{readable or 'branch'}-{hashlib.sha256(branch.encode('utf-8')).hexdigest()[:10]}"


def _damaged(path: Path, line: int, reason: str) -> TroupeError:
    return TroupeError(
        "events.malformed-record",
        problem=f"Line {line} of troupe's local file isn't valid: {reason}.",
        fix="This file is troupe's own local state, derived from the events. Delete it and troupe "
        "rebuilds it; followers then start again from the beginning.",
        path=str(path.absolute()),
        details={"line": line, "reason": reason},
    )


def _read_lines(path: Path) -> list[tuple[int, dict[str, object]]]:
    """Every complete line of ``path`` as a JSON object, trimming a torn last line."""
    if not path.exists():
        return []
    data = path.read_bytes()
    end = data.rfind(b"\n") + 1
    if end < len(data):
        with path.open("r+b") as handle:  # an interrupted append: it never took effect
            handle.truncate(end)
            handle.flush()
            os.fsync(handle.fileno())
    lines: list[tuple[int, dict[str, object]]] = []
    for number, raw in enumerate(data[:end].splitlines(), start=1):
        try:
            value = strict_json.loads(raw)
        except strict_json.StrictJSONError as error:
            raise _damaged(path, number, str(error)) from error
        if not isinstance(value, dict):
            raise _damaged(path, number, "a line must be a JSON object")
        lines.append((number, value))
    return lines


def _line(value: dict[str, object]) -> bytes:
    return strict_json.dumps(value).encode("utf-8") + b"\n"


@dataclass
class OrderLog:
    """One branch's notification order: ids[n - 1] is the event with notification id n."""

    path: Path
    epoch: str = ""
    ids: list[str] = field(default_factory=list)
    positions: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "OrderLog":
        log = cls(path)
        lines = _read_lines(path)
        if not lines:
            return log
        number, first = lines[0]
        if set(first) != {"epoch"} or not isinstance(first["epoch"], str) or not first["epoch"]:
            raise _damaged(path, number, 'the first line must be {"epoch": ...}')
        log.epoch = first["epoch"]
        for number, entry in lines[1:]:
            n, event = entry.get("n"), entry.get("event")
            if set(entry) != {"n", "event"} or not isinstance(event, str):
                raise _damaged(path, number, 'a line must be {"n": ..., "event": ...}')
            if n != len(log.ids) + 1 or isinstance(n, bool):
                raise _damaged(path, number, f"expected notification id {len(log.ids) + 1}")
            if event in log.positions:
                raise _damaged(path, number, f"event {event} is already ordered")
            log.positions[event] = n
            log.ids.append(event)
        return log

    @property
    def exists(self) -> bool:
        return bool(self.epoch)

    def ensure_epoch(self) -> str:
        """Start the order (with no events yet) if it hasn't started, and return its epoch."""
        if not self.exists:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.epoch = uuid.uuid4().hex
            append_bytes(self.path, _line({"epoch": self.epoch}))
        return self.epoch

    def append(self, events: list[str]) -> list[int]:
        """Give ``events`` the next notification ids, durably."""
        if not events:
            return []
        self.ensure_epoch()
        data = b""
        first = len(self.ids) + 1
        numbers = list(range(first, first + len(events)))
        data += b"".join(_line({"n": n, "event": e}) for n, e in zip(numbers, events, strict=True))
        append_bytes(self.path, data)
        for n, event in zip(numbers, events, strict=True):
            self.positions[event] = n
            self.ids.append(event)
        return numbers

    def rebuild(self, events: list[str]) -> None:
        """Replace the order with ``events`` under a new epoch."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.epoch = uuid.uuid4().hex
        self.ids = list(events)
        self.positions = {event: n for n, event in enumerate(events, start=1)}
        data = _line({"epoch": self.epoch}) + b"".join(
            _line({"n": n, "event": e}) for n, e in enumerate(events, start=1)
        )
        replace_file(self.path, data)


@dataclass
class TrackingLog:
    """Followers' positions on one branch, under the order's current epoch."""

    path: Path
    positions: dict[tuple[str, str], int] = field(default_factory=dict)
    """(epoch, application name) -> the highest notification id recorded."""

    @classmethod
    def load(cls, path: Path) -> "TrackingLog":
        log = cls(path)
        for number, entry in _read_lines(path):
            epoch, name, n = (
                entry.get("epoch"),
                entry.get("application_name"),
                entry.get("notification_id"),
            )
            if (
                set(entry) != {"epoch", "application_name", "notification_id"}
                or not isinstance(epoch, str)
                or not isinstance(name, str)
                or not isinstance(n, int)
                or isinstance(n, bool)
            ):
                raise _damaged(
                    path, number, "a line must be {epoch, application_name, notification_id}"
                )
            key = (epoch, name)
            log.positions[key] = max(log.positions.get(key, n), n)
        return log

    def max(self, epoch: str, name: str) -> int | None:
        return self.positions.get((epoch, name))

    def append(self, epoch: str, name: str, notification_id: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        append_bytes(
            self.path,
            _line({"epoch": epoch, "application_name": name, "notification_id": notification_id}),
        )
        self.positions[(epoch, name)] = notification_id
