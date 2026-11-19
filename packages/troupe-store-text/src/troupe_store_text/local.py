"""The local, gitignored files: the notification order and followers' positions (design D5).

Both live under ``.troupe/local/`` and belong to this clone alone, per branch:

- ``order/<branch-key>.jsonl``: ``{"epoch": ..., "after": n}``, then ``{"n": n + 1, "event":
  "<id>"}``, ``{"n": n + 2, ...}`` and so on. A new epoch means the order was rebuilt. Each order's
  ids are dense from just after ``after``, only ever appended, never renumbered; a branch's first
  order starts after 0, and a rebuilt one after the highest id ever issued there, so no id is
  reused (troupe-run/troupe#454).
- ``issued/<branch-key>.json``: ``{"issued": n}``: no id above n has been issued on the branch.
  It's kept apart from the order, so deleting the order file doesn't make ids start at 1 again.
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

from troupe.core import defaults, strict_json
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


_REBUILT_FIX = (
    "This file is troupe's own local state, derived from the events. Delete it and troupe "
    "rebuilds it; followers then start again from the beginning."
)
_ORDER_FIX = (
    "This file is troupe's own local state, derived from the events. Delete it and troupe "
    "rebuilds it, numbering after the highest notification id it has issued (kept in "
    "issued/); followers then start again from the beginning."
)
_ISSUED_FIX = (
    "This file records the highest notification id troupe has issued on this branch, so a "
    'rebuilt order never reuses one. Write it as {"issued": <n>}, with n at least the last id '
    "in the branch's order file (order/). If it and the order file are both deleted, ids start "
    "at 1 again, and any projection that keeps its position outside troupe must be rebuilt."
)


def _damaged(path: Path, line: int, reason: str, fix: str = _REBUILT_FIX) -> TroupeError:
    return TroupeError(
        "events.malformed-record",
        problem=f"Line {line} of troupe's local file isn't valid: {reason}.",
        fix=fix,
        path=str(path.absolute()),
        details={"line": line, "reason": reason},
    )


def _read_lines(
    path: Path, offset: int, first_line: int, *, trim: bool, fix: str = _REBUILT_FIX
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
            raise _damaged(path, number, str(error), fix) from error
        if not isinstance(value, dict):
            raise _damaged(path, number, "a line must be a JSON object", fix)
        lines.append((number, value))
    return lines, offset + end, raws[-1] if raws else b""


def _still_there(path: Path, first: bytes, offset: int, tail: bytes) -> bool:
    """Whether the file still starts with ``first`` (its epoch line) and still has ``tail`` ending
    at ``offset``,
    that is, whether it was only appended to since it was read that far. A rebuild changes the
    epoch; a repair (design D5) keeps it but moves every line after a dropped one."""
    with path.open("rb") as handle:
        if handle.readline(1024) != first:
            return False
        handle.seek(offset - len(tail))
        return handle.read(len(tail)) == tail


def _line(value: dict[str, object]) -> bytes:
    return strict_json.dumps(value).encode("utf-8") + b"\n"


def _named(entry: dict[str, object]) -> int:
    """The highest id an order line names: its ``n``, or an epoch line's ``after``; else 0."""
    named = [value for key in ("n", "after") if isinstance(value := entry.get(key), int)]
    return max((n for n in named if _count(n)), default=0)


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass
class IssuedMark:
    """The highest notification id that may have been issued on one branch (design D3 of
    follower-position-epoch). Written whole, by atomic replace, so it's never torn; raised ahead of
    the order, so it's never below it."""

    path: Path

    def read(self) -> int:
        """The mark, or 0 when there's none yet (the order's own last id then stands)."""
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return 0
        try:
            value = strict_json.loads(data)
        except strict_json.StrictJSONError as error:
            raise _damaged(self.path, 1, str(error), _ISSUED_FIX) from error
        if not isinstance(value, dict) or set(value) != {"issued"} or not _count(value["issued"]):
            raise _damaged(self.path, 1, 'the file must be {"issued": <n>}', _ISSUED_FIX)
        issued: int = value["issued"]
        return issued

    def raise_to(self, issued: int) -> int:
        """Raise the mark to at least ``issued``, never lowering it, and return it. The caller holds
        the write lock."""
        current = self.read()
        if issued > current:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            replace_file(self.path, _line({"issued": issued}))
            current = issued
        return current


@dataclass
class OrderLog:
    """One branch's notification order: ids[n - after - 1] is the event with notification id n.

    Other stores on the theatre, in this process or others, append to the same file, so the log
    catches up with it before each use (``catch_up``) rather than trusting what it read before."""

    path: Path
    epoch: str = ""
    after: int = 0
    """The order's ids run from after + 1 (follower-position-epoch design D2)."""
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
    seen: int = 0
    """The highest id this log has read or written, under any epoch: a new order starts after it."""
    reserved: int = 0
    """The issued mark as this log last read or wrote it: at most the mark on disk."""
    issued: IssuedMark = field(init=False)

    def __post_init__(self) -> None:
        self.issued = IssuedMark(self.path.parent.parent / "issued" / f"{self.path.stem}.json")

    @property
    def last(self) -> int:
        """The order's last id (``after`` when it has no events)."""
        return self.after + len(self.ids)

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
                or not _still_there(self.path, self._first(), self.offset, self.tail)
            )
        except FileNotFoundError:
            size, replaced = 0, self.offset > 0
        if replaced:
            self._forget()
        if size <= self.offset or self.conflict is not None:
            return
        lines, offset, tail = _read_lines(
            self.path, self.offset, self.lines + 1, trim=trim, fix=_ORDER_FIX
        )
        before = (self.epoch, self.after, len(self.ids), self.repeats)
        try:
            for number, entry in lines:
                self._take(number, entry)
                if self.conflict is not None:
                    # A rebuild replaces the whole file; nothing from this line on counts, except
                    # that the ids it names may have been issued, so the rebuilt order starts
                    # after them.
                    self.seen = max(self.seen, self.last, *(_named(entry) for _, entry in lines))
                    return
        except TroupeError:
            # A damaged line: take none of this read, so the next read refuses it again rather
            # than finding the lines before it a second time (as repeats).
            self.epoch, self.after, kept, self.repeats = before
            for event in self.ids[kept:]:
                del self.positions[event]
            del self.ids[kept:]
            raise
        self.offset, self.tail = offset, tail or self.tail
        self.lines += len(lines)

    def _first(self) -> bytes:
        return _line({"epoch": self.epoch, "after": self.after})

    def _forget(self) -> None:
        self.seen = max(self.seen, self.last)
        self.epoch, self.after, self.ids, self.positions = "", 0, [], {}
        self.offset, self.lines, self.tail, self.repeats, self.conflict = 0, 0, b"", 0, None

    def _take(self, number: int, entry: dict[str, object]) -> None:
        if "epoch" in entry:
            self._take_epoch(number, entry)
            return
        if not self.exists:
            raise _damaged(
                self.path, number, 'the first line must be {"epoch": ..., "after": ...}', _ORDER_FIX
            )
        n, event = entry.get("n"), entry.get("event")
        if (
            set(entry) != {"n", "event"}
            or not isinstance(event, str)
            or not isinstance(n, int)
            or isinstance(n, bool)
        ):
            raise _damaged(self.path, number, 'a line must be {"n": ..., "event": ...}', _ORDER_FIX)
        index = n - self.after - 1
        if 0 <= index < len(self.ids) and self.ids[index] == event:
            self.repeats += 1  # the same id for the same event, written again (design D5)
        elif n != self.last + 1:
            named = f", which names {self.ids[index]}" if 0 <= index < len(self.ids) else ""
            self.conflict = (
                number,
                f"expected notification id {self.last + 1}, found {n}{named}",
            )
        elif event in self.positions:
            self.conflict = (
                number,
                f"event {event} already has notification id {self.positions[event]}",
            )
        else:
            self.positions[event] = n
            self.ids.append(event)

    def _take_epoch(self, number: int, entry: dict[str, object]) -> None:
        epoch, after = entry.get("epoch"), entry.get("after")
        if not (
            set(entry) == {"epoch", "after"}
            and isinstance(epoch, str)
            and epoch
            and isinstance(after, int)
            and _count(after)
        ):
            raise _damaged(
                self.path, number, 'an epoch line must be {"epoch": ..., "after": <n>}', _ORDER_FIX
            )
        if self.exists:  # a stale store started the order again (design D5)
            self.conflict = (number, "the order starts again with a second epoch")
            return
        self.epoch, self.after = epoch, after

    @property
    def exists(self) -> bool:
        return bool(self.epoch)

    def _write(self, data: bytes, lines: int) -> None:
        append_bytes(self.path, data)
        self.offset += len(data)
        self.lines += lines
        self.tail = data[data.rfind(b"\n", 0, len(data) - 1) + 1 :]

    def _start(self) -> int:
        """Where a new order starts: after every id that may have been issued on the branch, by
        the mark, the order as it was, or anything this log has seen (design D3)."""
        return max(self.issued.read(), self.seen, self.last)

    def _reserve(self, last: int) -> None:
        """Raise the issued mark ahead of ``last`` before ids up to it are written (design D3)."""
        if last > self.reserved:
            self.reserved = self.issued.raise_to(last + defaults.ORDER_ID_RESERVE)

    def ensure_epoch(self) -> str:
        """Start the order (with no events yet) if it hasn't started, and return its epoch."""
        if not self.exists:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.epoch, self.after = uuid.uuid4().hex, self._start()
            self._write(self._first(), 1)
        return self.epoch

    def append(self, events: list[str]) -> list[int]:
        """Give ``events`` the next notification ids, durably. The caller holds the write lock and
        has caught up, so the file ends where this log has read to."""
        if not events:
            return []
        self.ensure_epoch()
        first = self.last + 1
        numbers = list(range(first, first + len(events)))
        self._reserve(numbers[-1])
        data = b"".join(_line({"n": n, "event": e}) for n, e in zip(numbers, events, strict=True))
        self._write(data, len(events))
        for n, event in zip(numbers, events, strict=True):
            self.positions[event] = n
            self.ids.append(event)
        self.seen = max(self.seen, self.last)
        return numbers

    def rebuild(self, events: list[str]) -> None:
        """Replace the order with ``events`` under a new epoch, numbered after every id that may
        have been issued on the branch, so none is reused (troupe-run/troupe#454)."""
        self._replace(uuid.uuid4().hex, self._start(), events)

    def repair(self) -> None:
        """Write the order again without its repeated lines, under the same epoch (design D5)."""
        self._replace(self.epoch, self.after, self.ids)

    def _replace(self, epoch: str, after: int, events: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._reserve(after + len(events))
        numbered = list(enumerate(events, start=after + 1))
        lines = [_line({"epoch": epoch, "after": after})] + [
            _line({"n": n, "event": e}) for n, e in numbered
        ]
        data = b"".join(lines)
        replace_file(self.path, data)
        self._forget()
        self.epoch, self.after = epoch, after
        self.ids = list(events)
        self.positions = {event: n for n, event in numbered}
        self.offset, self.lines, self.tail = len(data), len(lines), lines[-1]
        self.seen = max(self.seen, self.last)


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
        lines, offset, _ = _read_lines(self.path, self.offset, self.lines + 1, trim=trim)
        positions = dict(self.positions)  # taken only once every line is valid
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
            positions[key] = max(positions.get(key, n), n)
        self.positions, self.offset = positions, offset
        self.lines += len(lines)

    def max(self, epoch: str, name: str) -> int | None:
        return self.positions.get((epoch, name))

    def append(self, epoch: str, name: str, notification_id: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = _line({"epoch": epoch, "application_name": name, "notification_id": notification_id})
        append_bytes(self.path, data)
        self.offset += len(data)
        self.lines += 1
        self.positions[(epoch, name)] = notification_id
