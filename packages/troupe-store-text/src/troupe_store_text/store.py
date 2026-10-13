"""The text event store (spec: event-store; design D2-D7, D10; watch-event-segments D3-D5).

One TextStore per theatre directory and purpose in a process; the eventsourcing recorders in
recorders.py are views of it. It keeps:

- the segments under ``events/``, read incrementally (segments.py);
- which segments are visible on the current branch (design D7): those made on this branch, and
  every committed one; an uncommitted segment from another branch is left out, and reported;
- an index of the visible events: by id, by stream, each stream's heads, and the versions taken;
- this branch's notification order and followers' positions (local.py).

Every call takes a thread lock first, then (for a write) the theatre's write lock in ``local/``,
so threads queue in the process and processes queue across the theatre (design D10).

Listeners are told of every new event, whoever wrote it. Writes in this process tell them at once;
other processes' writes and segments git brings in are heard by watching ``events/`` through
troupe.platform, with an announced poll when it can't be watched (watch-event-segments D3-D5).
"""

import heapq
import os
import threading
import time
import weakref
from collections.abc import Callable, Hashable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from eventsourcing.persistence import IntegrityError, StoredEvent, Tracking

from troupe.core import defaults
from troupe.core.errors import TroupeError
from troupe.core.files import directory_lock, replace_file
from troupe.core.notices import Notice
from troupe.core.ulid import new_ulid
from troupe.core.vcs import Vcs
from troupe.platform.errors import WatchDirectoryMissingError, WatchUnavailableError
from troupe.platform.files import WaitCallback, append_bytes
from troupe.platform.paths import friendly as display
from troupe.platform.watching import DirectoryWatch, watch
from troupe_store_text.codec import Header, Record, encode_event, encode_header
from troupe_store_text.local import OrderLog, TrackingLog, branch_key
from troupe_store_text.segments import Segment

_UNSET: Hashable = object()

GITIGNORE = b"# troupe's local state: derived, per clone, never committed.\nlocal/\n"
GITATTRIBUTES = (
    b"# Event segments are byte-exact: never convert their line endings.\nevents/** -text\n"
)

Watcher = Callable[[Path], DirectoryWatch]
"""Starts watching a directory: troupe.platform.watching.watch, unless a test gives another."""


@dataclass(frozen=True)
class Head:
    id: str
    version: int
    path: Path
    line: int


class TextStore:
    """The events of one theatre (and purpose), as this clone sees them on its current branch."""

    def __init__(
        self,
        theatre: Path,
        vcs: Vcs,
        *,
        purpose: str = "events",
        lock_timeout: float = defaults.LOCK_TIMEOUT_SECONDS,
        lock_announce_after: float = defaults.LOCK_ANNOUNCE_AFTER_SECONDS,
        on_wait: WaitCallback | None = None,
        poll_seconds: float = defaults.SUBSCRIBE_POLL_SECONDS,
        check_seconds: float = defaults.SUBSCRIBE_CHECK_SECONDS,
        watcher: Watcher = watch,
    ) -> None:
        self.theatre = theatre
        self.vcs = vcs
        self.purpose = purpose
        troupe_dir = theatre / ".troupe"
        self.root = (
            troupe_dir if purpose == "events" else troupe_dir / "local" / "purposes" / purpose
        )
        self.events_dir = self.root / "events"
        self.local_dir = troupe_dir / "local" if purpose == "events" else self.root / "local"
        self.lock_timeout = lock_timeout
        self.lock_announce_after = lock_announce_after
        self.on_wait = on_wait
        self.poll_seconds = poll_seconds
        self.check_seconds = check_seconds
        self.watcher = watcher

        self._lock = threading.RLock()
        self._holding = False
        self._token: Hashable = _UNSET
        self._branch: str | None = None
        self._committed: frozenset[str] | None = None
        self._segments: dict[str, Segment] = {}
        self._visible: dict[str, bool] = {}
        self._own: set[str] = set()
        self._writing: Segment | None = None
        self._order: OrderLog | None = None
        self._tracking: TrackingLog | None = None
        self._order_key = ""
        self._rebuilt: list[Notice] = []
        self._listeners: set[threading.Event] = set()
        self._subscription: _Subscription | None = None
        self._delivered = 0  # the notification ids listeners have been told of
        self._polling: Notice | None = None  # while the subscription can only poll
        self._reset_index()

    # The index of visible events.

    def _reset_index(self) -> None:
        self._events: dict[str, Record] = {}
        self._recordings: dict[str, list[Record]] = {}
        self._streams: dict[UUID | str, dict[str, Record]] = {}
        self._heads: dict[UUID | str, set[str]] = {}
        self._has_child: set[str] = set()
        self._taken: dict[UUID | str, dict[int, str]] = {}

    def _index(self, record: Record) -> None:
        self._recordings.setdefault(record.id, []).append(record)
        if record.id in self._events:
            return  # the same event, recorded again elsewhere: one event, two recordings
        self._events[record.id] = record
        self._streams.setdefault(record.stream, {})[record.id] = record
        self._taken.setdefault(record.stream, {}).setdefault(record.version, record.id)
        heads = self._heads.setdefault(record.stream, set())
        if record.id not in self._has_child:
            heads.add(record.id)
        for parent in record.parents:
            self._has_child.add(parent)
            heads.discard(parent)

    # Reading the files.

    def refresh(self) -> None:
        """Bring the index up to date with the files and the working tree's state."""
        token = self.vcs.branch_token()
        rebuild = token != self._token
        if rebuild:
            self._token = token
            self._branch = self.vcs.branch()
            self._committed = None
        sizes = self._sizes()
        for name in set(self._segments) - set(sizes):
            del self._segments[name]
            rebuild = True
        added: list[tuple[Segment, list[Record]]] = []
        for name, size in sorted(sizes.items()):
            segment = self._segments.get(name)
            if segment is not None and size < segment.offset:
                segment = None  # it shrank: someone rewrote it; read it again from the start
                rebuild = True
            if segment is None:
                segment = Segment(self.events_dir / name)
                self._segments[name] = segment
            if size > segment.offset:
                records = segment.read_more(size)
                if records:
                    added.append((segment, records))
        if rebuild:
            self._reset_index()
            self._visible = {}
            for name in sorted(self._segments):
                self._add_segment(self._segments[name], self._segments[name].records)
            return
        for segment, records in added:
            self._add_segment(segment, records)

    def _sizes(self) -> dict[str, int]:
        try:
            entries = list(os.scandir(self.events_dir))
        except FileNotFoundError:
            return {}
        return {
            entry.name: entry.stat().st_size
            for entry in entries
            if entry.name.endswith(".jsonl") and entry.is_file()
        }

    def _add_segment(self, segment: Segment, records: list[Record]) -> None:
        name = segment.path.name
        if name not in self._visible:
            if segment.header is None:
                return  # nothing complete yet
            self._visible[name] = self._is_visible(segment.header, name)
            records = segment.records  # first sight of it: every complete batch so far
        if self._visible[name]:
            for record in records:
                self._index(record)

    def _is_visible(self, header: Header, name: str) -> bool:
        if header.branch == self._branch:
            return True
        if self._committed is None:
            relative = self.events_dir.relative_to(self.theatre).as_posix()
            self._committed = self.vcs.committed_under(relative)
        relative = (self.events_dir / name).relative_to(self.theatre).as_posix()
        return relative in self._committed

    # Notices: conditions a read should report (design D7, D4, D5).

    def notices(self) -> list[Notice]:
        with self._lock:
            self.refresh()
            found: list[Notice] = []
            for name, segment in sorted(self._segments.items()):
                if segment.header is not None and not self._visible.get(name, True):
                    found.append(_other_branch(segment, segment.header))
                if segment.incomplete and name not in self._own and self._torn(segment):
                    found.append(_incomplete(segment))
            if self._polling is not None:
                found.append(self._polling)
            found.extend(self._rebuilt)
            self._rebuilt = []
            return found

    def _torn(self, segment: Segment) -> bool:
        """Whether an incomplete batch at the end of ``segment`` is an interrupted write, rather
        than one another process is writing now. Only a writer holding the lock can be writing."""
        if self._holding or not self.local_dir.is_dir():
            return True
        try:
            with directory_lock(self.local_dir, timeout=0.0, announce_after=1.0):
                segment.read_more(segment.path.stat().st_size)
                return segment.incomplete
        except TroupeError as error:
            if error.code == "lock.timeout":
                return False
            raise

    # Ordering (design D5).

    def _load_local(self) -> OrderLog:
        return self._local()[0]

    def _local(self) -> tuple[OrderLog, TrackingLog]:
        """This branch's order and tracking files, loaded when the branch changes."""
        key = branch_key(self.vcs.name, self._branch)
        if self._order is None or self._tracking is None or key != self._order_key:
            self._order_key = key
            self._order = OrderLog.load(self.local_dir / "order" / f"{key}.jsonl")
            self._tracking = TrackingLog.load(self.local_dir / "tracking" / f"{key}.jsonl")
        return self._order, self._tracking

    def _pending(self) -> tuple[list[str], list[str]]:
        order = self._load_local()
        gone = [event for event in order.ids if event not in self._events]
        waiting = [event for event in self._events if event not in order.positions]
        return gone, waiting

    def ensure_ordered(self) -> OrderLog:
        """Give every visible event a notification id; rebuild the order if an ordered event has
        gone. Takes the write lock only when there is something to write."""
        gone, waiting = self._pending()
        if gone or waiting:
            with self._write_lock():
                self.refresh()
                self._order_locked()
        return self._load_local()

    def _order_locked(self) -> None:
        order = self._load_local()
        gone, waiting = self._pending()
        if gone:
            order.rebuild(self._replay_order(list(self._events)))
            self._rebuilt.append(_rebuilt(order.path, len(gone)))
        elif waiting:
            order.append(self._replay_order(waiting))

    def _replay_order(self, events: list[str]) -> list[str]:
        """``events`` in topological order by parents, then by session and line (design D5)."""
        pending = set(events)
        blocked: dict[str, int] = {}
        children: dict[str, list[str]] = {}
        for event in events:
            parents = [p for p in self._events[event].parents if p in pending]
            blocked[event] = len(parents)
            for parent in parents:
                children.setdefault(parent, []).append(event)
        ready = [(self._place(e), e) for e in events if blocked[e] == 0]
        heapq.heapify(ready)
        ordered: list[str] = []
        while ready:
            _, event = heapq.heappop(ready)
            ordered.append(event)
            for child in children.get(event, []):
                blocked[child] -= 1
                if blocked[child] == 0:
                    heapq.heappush(ready, (self._place(child), child))
        return ordered

    def _place(self, event: str) -> tuple[str, int]:
        record = self._events[event]
        return (record.path.stem, record.line)

    # Locks.

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        if self._holding:
            yield
            return
        self.local_dir.mkdir(parents=True, exist_ok=True)
        with directory_lock(
            self.local_dir,
            timeout=self.lock_timeout,
            announce_after=self.lock_announce_after,
            on_wait=self.on_wait,
        ):
            self._holding = True
            try:
                yield
            finally:
                self._holding = False

    # Reads.

    def select(
        self,
        stream: UUID | str,
        *,
        gt: int | None = None,
        lte: int | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> list[Record]:
        """The stream's events from its single head back to its latest settling event (or its
        start), filtered and ordered as the library asks (design D6)."""
        with self._lock:
            self.refresh()
            head = self._single_head(stream)
            if head is None:
                return []
            chain: list[Record] = []
            current = head
            while True:
                record = self._events[current]
                chain.append(record)
                if len(record.parents) != 1:
                    break  # a stream's first event, or a settling event
                current = record.parents[0]
            selected = [
                r
                for r in chain
                if (gt is None or r.version > gt) and (lte is None or r.version <= lte)
            ]
            selected.sort(key=lambda r: r.version, reverse=desc)
            return selected[:limit] if limit is not None else selected

    def _single_head(self, stream: UUID | str) -> str | None:
        events = self._streams.get(stream)
        if not events:
            return None
        self._check_parents(stream)
        heads = self._heads[stream]
        if len(heads) > 1:
            raise self._forked(stream, heads)
        return next(iter(heads))

    def _check_parents(self, stream: UUID | str) -> None:
        for record in sorted(self._streams[stream].values(), key=lambda r: (r.path.name, r.line)):
            for parent in record.parents:
                if parent not in self._events:
                    raise self._missing_parent(record, parent)

    def heads(self, stream: UUID | str) -> list[Head]:
        with self._lock:
            self.refresh()
            return [self._head_of(h) for h in sorted(self._heads.get(stream, ()))]

    def forks(self) -> list[UUID | str]:
        """Every stream with more than one head, without loading any (design D6)."""
        with self._lock:
            self.refresh()
            return sorted((s for s, h in self._heads.items() if len(h) > 1), key=str)

    def history(self, stream: UUID | str) -> list[Record]:
        """Every visible event of the stream, both sides of any fork, topologically."""
        with self._lock:
            self.refresh()
            return [
                self._events[e] for e in self._replay_order(list(self._streams.get(stream, {})))
            ]

    def recordings(self, event: str) -> list[Record]:
        """Every visible recording of the event: more than one when clones made the same change."""
        with self._lock:
            self.refresh()
            return list(self._recordings.get(event, []))

    def event(self, event: str) -> Record | None:
        with self._lock:
            self.refresh()
            return self._events.get(event)

    def notifications(
        self, low: int, limit: int, stop: int | None, topics: Sequence[str]
    ) -> list[tuple[int, Record]]:
        with self._lock:
            self.refresh()
            order = self.ensure_ordered()
            found: list[tuple[int, Record]] = []
            for n in range(max(low, 1), len(order.ids) + 1):
                if stop is not None and n > stop:
                    break
                record = self._events[order.ids[n - 1]]
                if topics and record.topic not in topics:
                    continue
                found.append((n, record))
                if len(found) >= limit:
                    break
            return found

    def max_notification_id(self) -> int | None:
        with self._lock:
            self.refresh()
            return len(self.ensure_ordered().ids) or None

    # Writes.

    def insert(
        self,
        stored_events: Sequence[StoredEvent],
        *,
        tracking: Tracking | None = None,
        settling_parents: Sequence[str] | None = None,
    ) -> list[int]:
        """Record a batch, all or nothing, and return its notification ids (design D4, D5)."""
        with self._lock, self._write_lock():
            self.refresh()
            self._order_locked()
            self._check_unique(stored_events)
            if tracking is not None:
                self._check_tracking(tracking)
            lines: list[bytes] = []
            batch_ids: list[str] = []
            if stored_events:
                batch = new_ulid()
                tips: dict[UUID | str, tuple[str, ...]] = {}
                for index, stored in enumerate(stored_events):
                    stream = stored.originator_id
                    if stream not in tips:
                        tips[stream] = self._parents_for(stream, index, settling_parents)
                    event_id, line = encode_event(
                        stream,
                        stored.originator_version,
                        stored.topic,
                        tips[stream],
                        stored.state,
                        (batch, index, len(stored_events)),
                    )
                    tips[stream] = (event_id,)
                    batch_ids.append(event_id)
                    lines.append(line)
                self._append(b"".join(lines))
                self.refresh()
            order, positions = self._local()
            numbers = order.append(batch_ids)
            self._delivered = len(order.ids)  # listeners here are told below, at once
            if tracking is not None:
                epoch = order.ensure_epoch()
                positions.append(epoch, tracking.application_name, tracking.notification_id)
        if stored_events:
            self._notify()
        return numbers

    def _check_unique(self, stored_events: Sequence[StoredEvent]) -> None:
        seen: set[tuple[UUID | str, int]] = set()
        for stored in stored_events:
            key = (stored.originator_id, stored.originator_version)
            if key in seen:
                msg = f"stream {key[0]} version {key[1]} appears twice in one batch"
                raise IntegrityError(msg)
            seen.add(key)
            if stored.originator_version in self._taken.get(stored.originator_id, {}):
                msg = f"stream {key[0]} version {key[1]} is already recorded"
                raise IntegrityError(msg)

    def _parents_for(
        self, stream: UUID | str, index: int, settling: Sequence[str] | None
    ) -> tuple[str, ...]:
        if settling is not None and index == 0:
            return self._settle_parents(stream, settling)
        head = self._single_head(stream)
        return () if head is None else (head,)

    def _settle_parents(self, stream: UUID | str, named: Sequence[str]) -> tuple[str, ...]:
        if stream in self._streams:
            self._check_parents(stream)
        heads = self._heads.get(stream, set())
        left_out = sorted(heads - set(named))
        unknown = sorted(set(named) - heads)
        if left_out or unknown or len(heads) < 2:
            raise TroupeError(
                "events.settle-incomplete",
                problem=f"A settling event for stream {stream} must name every head of the fork "
                f"({', '.join(sorted(heads)) or 'none'}); "
                + (f"it leaves out {', '.join(left_out)}" if left_out else "")
                + (f"; it names {', '.join(unknown)}, which isn't a head" if unknown else "")
                + ("; the stream isn't forked" if len(heads) < 2 else "")
                + ".",
                fix="Settle the fork again with its current heads as the parents.",
                details={
                    "stream": str(stream),
                    "heads": sorted(heads),
                    "left_out": left_out,
                    "unknown": unknown,
                },
            )
        return tuple(sorted(named))

    def _check_tracking(self, tracking: Tracking) -> None:
        order, positions = self._local()
        current = positions.max(order.epoch, tracking.application_name)
        if current is not None and tracking.notification_id <= current:
            msg = (
                f"tracking id {tracking.notification_id} is not greater than {current} for "
                f"{tracking.application_name!r}"
            )
            raise IntegrityError(msg)

    def insert_tracking(self, tracking: Tracking) -> None:
        with self._lock, self._write_lock():
            self.refresh()
            self._check_tracking(tracking)
            order, positions = self._local()
            positions.append(
                order.ensure_epoch(), tracking.application_name, tracking.notification_id
            )

    def max_tracking_id(self, application_name: str) -> int | None:
        with self._lock:
            self.refresh()
            order, positions = self._local()
            return positions.max(order.epoch, application_name) if order.exists else None

    def _append(self, data: bytes) -> None:
        """Append to this session's segment for the current branch, starting one if needed."""
        segment = self._writing
        if segment is None or segment.header is None or segment.header.branch != self._branch:
            session = new_ulid()
            header = Header(session=session, vcs=self.vcs.name, branch=self._branch)
            self._write_dotfiles()
            self.events_dir.mkdir(parents=True, exist_ok=True)
            path = self.events_dir / f"{session}.jsonl"
            data = encode_header(header) + data
            segment = Segment(path, header=header)
            self._writing = segment
            self._own.add(path.name)
        append_bytes(segment.path, data)

    def _write_dotfiles(self) -> None:
        if self.purpose != "events":
            return
        self.root.mkdir(parents=True, exist_ok=True)
        for name, content in ((".gitignore", GITIGNORE), (".gitattributes", GITATTRIBUTES)):
            if not (self.root / name).exists():
                replace_file(self.root / name, content)

    # Subscriptions (watch-event-segments design D3 to D5): the port's guarantee is that every new
    # event reaches a listener, whoever wrote it. Writes here notify at once. Other processes'
    # writes, and segments git brings in, are heard by watching the segments directory; when it
    # can't be watched, or its watch is found to miss a write, a poll takes over and says so.

    def listen(self, event: threading.Event) -> None:
        with self._lock:
            self._listeners.add(event)
            if self._subscription is None:
                self._subscription = _Subscription(self)
                self._subscription.start()

    def unlisten(self, event: threading.Event) -> None:
        with self._lock:
            self._listeners.discard(event)
            if not self._listeners and self._subscription is not None:
                self._subscription.stop()
                self._subscription = None
                self._polling = None

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener.set()

    def _deliver(self) -> bool:
        """Notify listeners if the order has changed since they were last told. Whether it had."""
        with self._lock:
            current = self.max_notification_id() or 0
            if current == self._delivered:
                return False
            self._delivered = current
            self._notify()
            return True

    def _watch_nearest(self) -> tuple[DirectoryWatch, bool]:
        """A watch on the segments directory, or while it doesn't exist yet, on its nearest
        existing ancestor in the theatre; and whether it is on the segments directory itself."""
        target = self.events_dir
        while True:
            try:
                return self.watcher(target), target == self.events_dir
            except WatchDirectoryMissingError:
                if target == self.theatre or target.parent == target:
                    raise
                target = target.parent

    # Errors.

    def _head_of(self, event: str) -> Head:
        record = self._events[event]
        return Head(event, record.version, record.path, record.line)

    def _forked(self, stream: UUID | str, heads: Iterable[str]) -> TroupeError:
        found = [self._head_of(h) for h in sorted(heads)]
        listed = "; ".join(f"{h.id} (version {h.version}, {display(h.path)})" for h in found)
        return TroupeError(
            "events.stream-forked",
            problem=f"Stream {stream} was appended to on two branches and has {len(found)} heads: "
            f"{listed}.",
            fix="Settle the fork: record a settling event that names every head as its parent and "
            "carries the settled state.",
            path=str(self.events_dir.absolute()),
            details={
                "stream": str(stream),
                "heads": [
                    {"id": h.id, "version": h.version, "file": str(h.path), "line": h.line}
                    for h in found
                ],
            },
        )

    def _missing_parent(self, record: Record, parent: str) -> TroupeError:
        elsewhere = [
            segment.path
            for name, segment in sorted(self._segments.items())
            if not self._visible.get(name, True) and any(r.id == parent for r in segment.records)
        ]
        where = (
            f" It is only in {', '.join(display(p) for p in elsewhere)}, made on another branch."
            if elsewhere
            else ""
        )
        return TroupeError(
            "events.missing-parent",
            problem=f"Line {record.line} of an event segment follows event {parent}, which isn't "
            f"here.{where}",
            fix="Restore the file that held the missing event, or remove this file too.",
            path=str(record.path.absolute()),
            details={
                "line": record.line,
                "event": record.id,
                "missing_parent": parent,
                "only_in": [str(p) for p in elsewhere],
            },
        )


def _other_branch(segment: Segment, header: Header) -> Notice:
    return Notice(
        "events.other-branch",
        problem=f"Events made on branch {header.branch!r} and not committed were left out.",
        fix=f"To keep them, switch back to {header.branch!r} and commit them. If you don't want "
        "them, delete the file.",
        path=str(segment.path.absolute()),
        details={"branch": header.branch, "session": header.session},
    )


def _incomplete(segment: Segment) -> Notice:
    return Notice(
        "events.incomplete-batch",
        problem="This segment ends in a batch whose write was interrupted, so it was left out. "
        "It never took effect.",
        fix="Remove the trailing lines after the last complete batch, or leave them: they are "
        "ignored.",
        path=str(segment.path.absolute()),
        details={"line": segment.lines + 1},
    )


def _rebuilt(path: Path, gone: int) -> Notice:
    return Notice(
        "events.order-rebuilt",
        problem=f"{gone} event(s) in the local order are no longer here (a file was removed, or "
        "a reset dropped them), so the order was rebuilt and followers start again.",
        fix="Nothing to do: projections are rebuilt from the events. Restore the removed file if "
        "it was removed by mistake.",
        path=str(path.absolute()),
        details={"gone": gone},
    )


class _Subscription:
    """The thread that tells a store's listeners of other writers' events (watch-event-segments
    design D3 to D5). It waits on a watch of the segments directory; a wake costs one incremental
    refresh. Every ``check_seconds`` it refreshes anyway, and a new event its watch didn't report
    means the file system doesn't deliver: it then polls every ``poll_seconds``, and says so."""

    def __init__(self, store: TextStore) -> None:
        self.store = store
        self._stopped = threading.Event()
        self._watch: DirectoryWatch | None = None
        self._on_events = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="troupe-subscription")

    def start(self) -> None:
        """Set up the watch before returning, so a refusal is in the store's notices at once.
        Called with the store's lock held."""
        store = self.store
        store._delivered = store.max_notification_id() or 0
        try:
            self._watch, self._on_events = store._watch_nearest()
        except (WatchUnavailableError, WatchDirectoryMissingError) as error:
            store._polling = _subscription_polling(store, "watch-refused", str(error))
        self._thread.start()

    def stop(self) -> None:
        """Called with the store's lock held."""
        self._stopped.set()
        if self._watch is not None:
            self._watch.close()

    def _run(self) -> None:
        store = self.store
        reported = False  # whether the watch reported anything since the last check
        next_check = time.monotonic() + store.check_seconds
        try:
            while not self._stopped.is_set():
                current = self._watch
                if current is None:  # polling: refused, or found to miss writes
                    if not self._stopped.wait(store.poll_seconds):
                        store._deliver()
                    continue
                try:
                    changed = current.wait(max(0.0, next_check - time.monotonic()))
                except WatchDirectoryMissingError:
                    changed = True  # the watched directory went: watch its nearest ancestor
                    self._on_events = False
                if self._stopped.is_set():
                    return
                if changed:
                    reported = True
                    if not self._on_events:
                        self._rearm(current)
                    store._deliver()
                if time.monotonic() >= next_check:
                    if store._deliver() and not reported:
                        self._fall_back(
                            "watch-missed-write",
                            "an event was recorded that the watch didn't report",
                        )
                    reported = False
                    next_check = time.monotonic() + store.check_seconds
        finally:
            with store._lock:
                if self._watch is not None:
                    self._watch.close()

    def _rearm(self, current: DirectoryWatch) -> None:
        """Move the watch nearer the segments directory once a nearer directory exists."""
        store = self.store
        nearest = store.events_dir
        while not nearest.is_dir() and nearest != store.theatre and nearest.parent != nearest:
            nearest = nearest.parent
        if nearest == current.directory and current.directory.is_dir():
            return
        try:
            replacement, on_events = store._watch_nearest()
        except (WatchUnavailableError, WatchDirectoryMissingError) as error:
            self._fall_back("watch-refused", str(error))
            return
        with store._lock:
            if self._stopped.is_set():
                replacement.close()
                return
            self._watch, self._on_events = replacement, on_events
        current.close()

    def _fall_back(self, reason: str, detail: str) -> None:
        store = self.store
        with store._lock:
            if self._watch is not None:
                self._watch.close()
            self._watch = None
            if not self._stopped.is_set():
                store._polling = _subscription_polling(store, reason, detail)


def _subscription_polling(store: TextStore, reason: str, detail: str) -> Notice:
    """events.subscription-polling, with the text store's reason (watch-event-segments D5)."""
    directory = display(store.events_dir)
    every = f"{store.poll_seconds:g}"
    if reason == "watch-refused":
        problem = (
            f"troupe can't watch {directory} for events other processes record ({detail}), so "
            f"it looks for them every {every} s instead."
        )
        fix = (
            "Events still arrive, up to SUBSCRIBE_POLL_SECONDS late. To be told of them at once, "
            + (
                "raise the limit the reason names."
                if "max_user" in detail
                else "keep the theatre on a local disk."
            )
        )
    else:
        problem = (
            f"An event another process recorded wasn't reported by the watch on {directory}: "
            f"this file system accepts watches but doesn't deliver them, so troupe looks for "
            f"new events every {every} s instead."
        )
        fix = (
            "Events still arrive, up to SUBSCRIBE_POLL_SECONDS late. To be told of them at once, "
            "keep the theatre on a local file system, not a container bind mount or a network "
            "share."
        )
    return Notice(
        "events.subscription-polling",
        problem=problem,
        fix=fix,
        path=str(store.events_dir.absolute()),
        details={"reason": reason, "detail": detail, "poll_seconds": store.poll_seconds},
    )


_stores: "weakref.WeakValueDictionary[tuple[str, str], TextStore]" = weakref.WeakValueDictionary()
_stores_guard = threading.Lock()


def shared_store(
    theatre: Path,
    vcs_factory: Callable[[], Vcs],
    purpose: str = "events",
    *,
    poll_seconds: float = defaults.SUBSCRIBE_POLL_SECONDS,
    check_seconds: float = defaults.SUBSCRIBE_CHECK_SECONDS,
    watcher: Watcher = watch,
) -> TextStore:
    """The one TextStore for this theatre and purpose in this process, so every recorder over the
    same directory shares one lock and one index."""
    key = (str(theatre.resolve()), purpose)
    with _stores_guard:
        store = _stores.get(key)
        if store is None:
            store = TextStore(
                theatre,
                vcs_factory(),
                purpose=purpose,
                poll_seconds=poll_seconds,
                check_seconds=check_seconds,
                watcher=watcher,
            )
            _stores[key] = store
        return store
