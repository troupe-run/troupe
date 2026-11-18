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


def _read_lines(
    path: Path, offset: int, first_line: int, *, trim: bool
) -> tuple[list[tuple[int, dict[str, object]]], int, bytes]:
    """Every complete line of ``path`` after byte ``offset`` as a JSON object, numbered from
    ``first_line``; the offset just past the last complete line; and that line's bytes.

    An incomplete last line is left unread. With ``trim`` (the caller holds the write lock, so no
    one else is appending), it's an interrupted append that never took effect, and is cut off;
    without it, it may be another writer's append in progress, so it's left alone."""
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
    except FileNotFoundError:
        return [], offset, b""
    end = data.rfind(b"\n") + 1
    if trim and end < len(data):
        with path.open("r+b") as handle:  # an interrupted append: it never took effect
            handle.truncate(offset + end)
            handle.flush()
            os.fsync(handle.fileno())
    lines: list[tuple[int, dict[str, object]]] = []
    raws = data[:end].splitlines(keepends=True)
    for number, raw in enumerate(raws, start=first_line):
        try:
            value = strict_json.loads(raw)
        except strict_json.StrictJSONError as error:
            raise _damaged(path, number, str(error)) from error
        if not isinstance(value, dict):
            raise _damaged(path, number, "a line must be a JSON object")
        lines.append((number, value))
    return lines, offset + end, raws[-1] if raws else b""


def _still_there(path: Path, epoch: str, offset: int, tail: bytes) -> bool:
    """Whether the file still starts with ``epoch`` and still has ``tail`` ending at ``offset``,
    that is, whether it was only appended to since it was read that far. A rebuild changes the
    epoch; a repair (design D5) keeps it but moves every line after a dropped one."""
    with path.open("rb") as handle:
        if handle.readline(1024) != _line({"epoch": epoch}):
            return False
        handle.seek(offset - len(tail))
        return handle.read(len(tail)) == tail


def _line(value: dict[str, object]) -> bytes:
    return strict_json.dumps(value).encode("utf-8") + b"\n"


@dataclass
class OrderLog:
    """One branch's notification order: ids[n - 1] is the event with notification id n.

    Other stores on the theatre, in this process or others, append to the same file, so the log
    catches up with it before each use (``catch_up``) rather than trusting what it read before."""

    path: Path
    epoch: str = ""
    ids: list[str] = field(default_factory=list)
    positions: dict[str, int] = field(default_factory=dict)
    offset: int = 0
    """How many bytes of the file have been read: everything before is in ``ids``."""
    lines: int = 0

    tail: bytes = b""
    """The last complete line read, which ends at ``offset``."""
    repeats: int = 0
    """Lines read that repeat an id already given to the same event (design D5): left out."""
    conflict: tuple[int, str] | None = None
    """The first line read that's out of sequence (design D5), and why. Reading stops there."""

    @classmethod
    def load(cls, path: Path, *, trim: bool = False) -> "OrderLog":
        log = cls(path)
        log.catch_up(trim=trim)
        return log

    def catch_up(self, *, trim: bool) -> None:
        """Read what other stores appended since this log last looked. A file that's gone, or was
        rewritten (a rebuild, or a repair) is read again whole. ``trim``: the caller holds the write
        lock (see ``_read_lines``)."""
        try:
            size = self.path.stat().st_size
            replaced = self.offset > 0 and (
                size < self.offset
                or not _still_there(self.path, self.epoch, self.offset, self.tail)
            )
        except FileNotFoundError:
            size, replaced = 0, self.offset > 0
        if replaced:
            self._forget()
        if size <= self.offset or self.conflict is not None:
            return
        lines, offset, tail = _read_lines(self.path, self.offset, self.lines + 1, trim=trim)
        for number, entry in lines:
            self._take(number, entry)
            if self.conflict is not None:
                return  # a rebuild replaces the whole file; nothing after this line counts
        self.offset, self.tail = offset, tail or self.tail
        self.lines += len(lines)

    def _forget(self) -> None:
        self.epoch, self.ids, self.positions = "", [], {}
        self.offset, self.lines, self.tail, self.repeats, self.conflict = 0, 0, b"", 0, None

    def _take(self, number: int, entry: dict[str, object]) -> None:
        epoch = entry.get("epoch")
        if set(entry) == {"epoch"} and isinstance(epoch, str) and epoch:
            if self.exists:  # a stale store started the order again (design D5)
                self.conflict = (number, "the order starts again with a second epoch")
            else:
                self.epoch = epoch
            return
        if not self.exists:
            raise _damaged(self.path, number, 'the first line must be {"epoch": ...}')
        n, event = entry.get("n"), entry.get("event")
        if (
            set(entry) != {"n", "event"}
            or not isinstance(event, str)
            or not isinstance(n, int)
            or isinstance(n, bool)
        ):
            raise _damaged(self.path, number, 'a line must be {"n": ..., "event": ...}')
        if 1 <= n <= len(self.ids) and self.ids[n - 1] == event:
            self.repeats += 1  # the same id for the same event, written again (design D5)
        elif n != len(self.ids) + 1:
            named = f", which names {self.ids[n - 1]}" if 1 <= n <= len(self.ids) else ""
            self.conflict = (
                number,
                f"expected notification id {len(self.ids) + 1}, found {n}{named}",
            )
        elif event in self.positions:
            self.conflict = (
                number,
                f"event {event} already has notification id {self.positions[event]}",
            )
        else:
            self.positions[event] = n
            self.ids.append(event)

    @property
    def exists(self) -> bool:
        return bool(self.epoch)

    def _write(self, data: bytes, lines: int) -> None:
        append_bytes(self.path, data)
        self.offset += len(data)
        self.lines += lines
        self.tail = data[data.rfind(b"\n", 0, len(data) - 1) + 1 :]

    def ensure_epoch(self) -> str:
        """Start the order (with no events yet) if it hasn't started, and return its epoch."""
        if not self.exists:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.epoch = uuid.uuid4().hex
            self._write(_line({"epoch": self.epoch}), 1)
        return self.epoch

    def append(self, events: list[str]) -> list[int]:
        """Give ``events`` the next notification ids, durably. The caller holds the write lock and
        has caught up, so the file ends where this log has read to."""
        if not events:
            return []
        self.ensure_epoch()
        first = len(self.ids) + 1
        numbers = list(range(first, first + len(events)))
        data = b"".join(_line({"n": n, "event": e}) for n, e in zip(numbers, events, strict=True))
        self._write(data, len(events))
        for n, event in zip(numbers, events, strict=True):
            self.positions[event] = n
            self.ids.append(event)
        return numbers

    def rebuild(self, events: list[str]) -> None:
        """Replace the order with ``events`` under a new epoch."""
        self._replace(uuid.uuid4().hex, events)

    def repair(self) -> None:
        """Write the order again without its repeated lines, under the same epoch (design D5)."""
        self._replace(self.epoch, self.ids)

    def _replace(self, epoch: str, events: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [_line({"epoch": epoch})] + [
            _line({"n": n, "event": e}) for n, e in enumerate(events, start=1)
        ]
        data = b"".join(lines)
        replace_file(self.path, data)
        self._forget()
        self.epoch = epoch
        self.ids = list(events)
        self.positions = {event: n for n, event in enumerate(events, start=1)}
        self.offset, self.lines, self.tail = len(data), len(lines), lines[-1]


@dataclass
class TrackingLog:
    """Followers' positions on one branch, under the order's current epoch. Like the order, it
    catches up with the file before each use."""

    path: Path
    positions: dict[tuple[str, str], int] = field(default_factory=dict)
    """(epoch, application name) -> the highest notification id recorded."""
    offset: int = 0
    lines: int = 0

    @classmethod
    def load(cls, path: Path, *, trim: bool = False) -> "TrackingLog":
        log = cls(path)
        log.catch_up(trim=trim)
        return log

    def catch_up(self, *, trim: bool) -> None:
        """Read positions other stores recorded since this log last looked; read the file again
        whole if it's gone or shorter than what was read (it was deleted)."""
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            size = 0
        if size < self.offset:
            self.positions, self.offset, self.lines = {}, 0, 0
        if size <= self.offset:
            return
        lines, self.offset, _ = _read_lines(self.path, self.offset, self.lines + 1, trim=trim)
        self.lines += len(lines)
        for number, entry in lines:
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
                    self.path, number, "a line must be {epoch, application_name, notification_id}"
                )
            key = (epoch, name)
            self.positions[key] = max(self.positions.get(key, n), n)

    def max(self, epoch: str, name: str) -> int | None:
        return self.positions.get((epoch, name))

    def append(self, epoch: str, name: str, notification_id: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = _line({"epoch": epoch, "application_name": name, "notification_id": notification_id})
        append_bytes(self.path, data)
        self.offset += len(data)
        self.lines += 1
        self.positions[(epoch, name)] = notification_id
