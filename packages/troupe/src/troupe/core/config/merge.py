"""Working out config from its stream's whole history, branches merged (spec: config; config-model
design D3, D4; #135, #136).

Config is read from every event of its stream, both sides of any fork, never from the library's
``load``. A settling event is a join: its parents are every head it settled, and the merge reads
the history through it, never its state (a snapshot for the library), so every clone that settles
the same heads agrees.

**Points and latest writes.** Each path an entry names is a point. The writes that cover a point
are the entries at that path or at a group above it. A point's latest writes are the covering
writes that no later covering write follows (in the chain of parents). One latest write: no
contest. Several are concurrent, from lines of history that split.

**A line's net change.** A latest write's line is the covering writes behind it that the other
latest writes don't descend from. A line whose writes are all at the point itself, and whose net
change (its first ``before`` to its last ``after``) ends where it began, changed nothing: it drops
out. Of those left, lines that leave the point the same agree; otherwise their changes are in
conflict, whole.

**Replay.** Config is every entry replayed in the history's order, leaving out the lines that
dropped out, and both sides of every conflict. Where that leaves out every latest write of a point,
the writes beneath them decide, so they're contested by the same rule, until one is left or a line
stays in (#190); only the first contest's conflict is reported. Entries that are left and
concurrent then never overlap, so their order can't change the result, and every clone works out
the same config.

**Conflicts from validation.** When the merged config breaks a rule (``kinds.problems``), the
changes since the split that touched what broke it are in conflict too.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from troupe.core import strict_json
from troupe.core.config.aggregate import CHANGED
from troupe.core.config.changes import Tree, apply, dotted, value_hash
from troupe.core.config.kinds import ACTORS, problems
from troupe.core.errors import TroupeError
from troupe.core.events.port import RecordedEvent

Point = tuple[str, ...]


@dataclass(frozen=True)
class Change:
    """One recorded ``Config.Changed``: who made it, when, and every entry in it."""

    id: str
    change: str
    actor: dict[str, Any]
    at: str
    entries: tuple[dict[str, Any], ...]
    files: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Conflict:
    """Changes from lines of history that can't both hold: they left the same values different
    (``paths``), or together they make config break a rule (``rule``)."""

    paths: tuple[Point, ...]
    changes: tuple[Change, ...]
    rule: str | None = None

    def describe(self) -> str:
        where = ", ".join(dotted(path) for path in self.paths)
        made = "; ".join(
            f"change {c.change} by {c.actor.get('id', 'someone unknown')} at {c.at}"
            for c in self.changes
        )
        if self.rule is not None:
            return f"{where}: together these changes break a rule ({self.rule}): {made}"
        return f"{where}: these changes set it differently: {made}"


@dataclass(frozen=True)
class Merged:
    """Config as the stream's history works it out."""

    config: Tree
    conflicts: tuple[Conflict, ...]
    heads: tuple[str, ...]
    """The ids of the stream's heads, sorted: the config version a run records."""
    version: int
    """The stream's highest version: a new event's is one more."""
    changes: tuple[Change, ...] = ()
    files: dict[str, frozenset[str]] = field(default_factory=dict)
    """Every hash troupe recorded for each config file, on any line of history."""


@dataclass(frozen=True)
class _Write:
    event: str
    index: int
    entry: dict[str, Any]

    @property
    def path(self) -> Point:
        return tuple(self.entry["path"])


def _covers(path: Point, point: Point) -> bool:
    return point[: len(path)] == path


def merge(history: Sequence[RecordedEvent], *, extra: Change | None = None) -> Merged:
    """Config from ``history``, the config stream's every event, in the store's order. With
    ``extra``, as though that change were recorded after every head: how a change made while there
    are conflicts is checked to see whether it resolves them."""
    events = {record.id: record for record in history}
    _check_parents(history, events)
    order = [record.id for record in history]
    parents = {record.id: tuple(record.parents) for record in history}
    changes = {r.id: _change(r) for r in history if r.topic == CHANGED}
    heads = sorted(set(order) - {p for ps in parents.values() for p in ps})
    if extra is not None:
        changes[extra.id] = extra
        parents[extra.id] = tuple(heads)
        order.append(extra.id)
    ancestors = _ancestors(order, parents)
    writes = [
        _Write(event, index, entry)
        for event in order
        if event in changes
        for index, entry in enumerate(changes[event].entries)
    ]
    skipped: set[tuple[str, int]] = set()
    conflicts: list[Conflict] = []
    for point in sorted({write.path for write in writes}):
        found = _contest(point, writes, ancestors)
        if found is None:
            continue
        drop, conflicting = found
        skipped |= drop
        if conflicting:
            events_in = sorted({w.event for w in conflicting}, key=order.index)
            conflicts.append(Conflict((point,), tuple(changes[e] for e in events_in)))
    config = apply_in_order(writes, skipped)
    conflicts = _grouped(conflicts)
    tips = heads if extra is None else [extra.id]
    conflicts += _invalid(config, writes, ancestors, changes, tips, conflicts)
    files: dict[str, set[str]] = {}
    for change in changes.values():
        for written in change.files:
            if "hash" in written:
                files.setdefault(written["path"], set()).add(written["hash"])
    return Merged(
        config=config,
        conflicts=tuple(conflicts),
        heads=tuple(heads),
        version=max((record.version for record in history), default=0),
        changes=tuple(changes[e] for e in order if e in changes),
        files={path: frozenset(hashes) for path, hashes in files.items()},
    )


def _change(record: RecordedEvent) -> Change:
    state = strict_json.loads(record.state)
    if not isinstance(state, dict):
        msg = f"config event {record.id} has no payload object"
        raise TypeError(msg)
    lineage = record.lineage or {}
    return Change(
        id=record.id,
        change=str(lineage.get("change", "")),
        actor=dict(lineage.get("actor", {"kind": "unknown"})),
        at=str(lineage.get("at", "")),
        entries=tuple(state.get("changes", ())),
        files=tuple(state.get("files", ())),
    )


def _check_parents(history: Sequence[RecordedEvent], events: dict[str, RecordedEvent]) -> None:
    for record in history:
        for parent in record.parents:
            if parent not in events:
                raise TroupeError(
                    "events.missing-parent",
                    problem=f"Line {record.line} of an event segment follows event {parent}, "
                    "which isn't here.",
                    fix="Restore the file that held the missing event (git restore), or, if it "
                    "was removed on purpose, remove this file too.",
                    path=str(record.path),
                    details={"missingParent": parent, "onlyIn": []},
                )


def _ancestors(
    order: Sequence[str], parents: dict[str, tuple[str, ...]]
) -> dict[str, frozenset[str]]:
    found: dict[str, frozenset[str]] = {}
    for event in order:
        mine: set[str] = set()
        for parent in parents.get(event, ()):
            mine.add(parent)
            mine |= found.get(parent, frozenset())
        found[event] = frozenset(mine)
    return found


def _contest(
    point: Point, writes: Sequence[_Write], ancestors: dict[str, frozenset[str]]
) -> tuple[set[tuple[str, int]], list[_Write]] | None:
    """For a point with concurrent latest writes: the writes to leave out of replay, and the
    latest writes left in conflict (empty when they agree).

    When no latest write stays in (they conflict, or every line drops out), the writes beneath
    decide, so they're contested again by the same rule, until one is left or a line stays in.
    Only the first round's conflict is reported (#190)."""
    found = _round(point, writes, ancestors)
    if found is None:
        return None
    drop, conflicting, latest = found
    while not {(w.event, w.index) for w in latest} - drop:
        left = [w for w in writes if (w.event, w.index) not in drop]
        beneath = _round(point, left, ancestors)
        if beneath is None:
            break  # one write is left, or none
        drop |= beneath[0]
        latest = beneath[2]
    return drop, conflicting


def _round(
    point: Point, writes: Sequence[_Write], ancestors: dict[str, frozenset[str]]
) -> tuple[set[tuple[str, int]], list[_Write], list[_Write]] | None:
    """One round of a point's contest: the writes to leave out, the latest writes left in
    conflict, and every latest write."""
    covering = [w for w in writes if _covers(w.path, point)]
    latest_by_event: dict[str, _Write] = {}
    for write in covering:
        if any(write.event in ancestors[o.event] for o in covering):
            continue  # a later covering write follows it
        current = latest_by_event.get(write.event)
        if current is None or len(write.path) >= len(current.path):
            latest_by_event[write.event] = write  # in one event, the deeper entry applies last
    if len(latest_by_event) <= 1:
        return None
    latest = list(latest_by_event.values())
    lines: dict[str, list[_Write]] = {}
    for write in latest:
        others = set().union(*({o.event} | ancestors[o.event] for o in latest if o is not write))
        mine = ancestors[write.event] | {write.event}
        lines[write.event] = [w for w in covering if w.event in mine and w.event not in others]
    drop: set[tuple[str, int]] = set()
    left: list[_Write] = []
    for write in latest:
        line = lines[write.event]
        if all(w.path == point for w in line) and _ends_where_it_began(line):
            drop |= {(w.event, w.index) for w in line}
        else:
            left.append(write)
    if len({_effect(w, point) for w in left}) <= 1:
        return drop, [], latest
    for write in latest:
        drop |= {(w.event, w.index) for w in lines[write.event]}
    return drop, left, latest


def _ends_where_it_began(line: Sequence[_Write]) -> bool:
    began = line[0].entry.get("before")
    last = line[-1].entry
    ended = value_hash(last["after"]) if "after" in last else None
    return began == ended


def _effect(write: _Write, point: Point) -> tuple[str, ...]:
    if write.path == point and "after" in write.entry:
        return ("after", value_hash(write.entry["after"]))
    return ("absent",)


def apply_in_order(writes: Iterable[_Write], skipped: set[tuple[str, int]]) -> Tree:
    config: Tree = {}
    batch: list[dict[str, Any]] = []
    current: str | None = None
    for write in writes:
        if write.event != current:
            config = apply(config, batch)
            batch, current = [], write.event
        if (write.event, write.index) not in skipped:
            batch.append(write.entry)
    return apply(config, batch)


def _grouped(conflicts: Sequence[Conflict]) -> list[Conflict]:
    """Conflicts between the same changes, as one conflict naming every path."""
    grouped: dict[tuple[str, ...], list[Conflict]] = {}
    for conflict in conflicts:
        grouped.setdefault(tuple(c.id for c in conflict.changes), []).append(conflict)
    return [
        Conflict(tuple(p for c in group for p in c.paths), group[0].changes)
        for group in grouped.values()
    ]


def _invalid(
    config: Tree,
    writes: Sequence[_Write],
    ancestors: dict[str, frozenset[str]],
    changes: dict[str, Change],
    heads: Sequence[str],
    structural: Sequence[Conflict],
) -> list[Conflict]:
    """When merged config breaks a rule: the changes since the split that touched what broke it.
    Not for an actor that already has a conflict: its values change when that's resolved."""
    if len(heads) < 2:
        return []
    common = frozenset.intersection(*(ancestors[h] | {h} for h in heads))
    found: list[Conflict] = []
    seen: set[Point] = set()
    for problem in problems(config):
        where = problem.path[:2] if problem.path[:1] == (ACTORS,) else problem.path[:1]
        if where in seen or any(_overlaps(p, where) for c in structural for p in c.paths):
            continue
        touched = [
            w.event
            for w in writes
            if w.event not in common and w.event in changes and _overlaps(w.path, where)
        ]
        events_in = list(dict.fromkeys(touched))
        if len(events_in) < 2:
            continue  # one line alone broke it: refused when it was recorded, never by a merge
        seen.add(where)
        found.append(Conflict((where,), tuple(changes[e] for e in events_in), rule=problem.rule))
    return found


def _overlaps(path: Point, where: Point) -> bool:
    return _covers(path, where) or _covers(where, path)
