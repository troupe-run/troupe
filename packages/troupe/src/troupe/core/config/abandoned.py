"""Abandoned edits: the round trip a sweep closes, whether it can be dropped, and the record of
the ones a person kept (spec: config-hand-edits; abandoned-edits design D1, D2, D3, D7).

When a sweep records a hand edit that puts a file's values back to what they were before an
earlier run of recorded changes to it, whoever made them, those changes and the edit back are a
round trip (owner, 2026-11-23, on #45). It's found from the config stream alone: values are
compared, never bytes, and git is never asked (a stash looks like any restore; #1).

A round trip can be dropped only while that's safe: it changes nothing outside its files, nothing
follows it in the config stream, no run names it in its config version, and each of its events
is alone in an uncommitted segment of this branch. The store removes whole segments only
(``EventRecorder.drop``); this module decides what to ask it to remove.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from troupe.core import strict_json
from troupe.core.config import aggregate
from troupe.core.config.changes import Tree, apply, get
from troupe.core.config.kinds import ACTORS, CHARACTER
from troupe.core.config.merge import merge
from troupe.core.config.reading import owner
from troupe.core.events import EventStore
from troupe.core.events.port import RecordedEvent
from troupe.core.notices import Notice
from troupe.core.theatre import THEATRE_DIR

Point = tuple[str, ...]
Reason = Literal["changes-more", "built-on", "run", "committed", "shares-segment"]


@dataclass(frozen=True)
class _Scope:
    """The part of config one file owns: ``group`` whole, or its fields but the character, or
    only its character (design D1)."""

    group: tuple[str, str]
    part: Literal["whole", "fields", "character"]

    def value(self, config: Mapping[str, Any]) -> object:
        found = get(config, self.group)
        if not isinstance(found, Mapping):
            return None
        if self.part == "whole":
            return dict(found)
        if self.part == "character":
            return found.get(CHARACTER)
        fields = {k: v for k, v in found.items() if k != CHARACTER}
        return fields or None


@dataclass(frozen=True)
class RoundTrip:
    """The round trip the sweep whose change id is ``closing`` closed (design D1)."""

    closing: str
    events: tuple[str, ...]
    """Its config events, first change to the closing sweep's last edit, in chain order."""
    changes: tuple[str, ...]
    """Their change ids, in order, each once."""
    files: tuple[str, ...]
    """The files whose values went back, relative to .troupe/."""
    outside: str | None
    """The change id of the first of its events that changes a value outside its files' parts:
    dropping it would undo more than the files (design D3, ``changes-more``)."""


@dataclass(frozen=True)
class Blocked:
    """Why a round trip can't be dropped (design D3)."""

    reason: Reason
    blocker: str | None = None
    """The change id, run id or segment that blocks it, when there is one."""

    def describe(self) -> str:
        match self.reason:
            case "changes-more":
                return f"change {self.blocker} among them changes other values too"
            case "built-on":
                return f"change {self.blocker} was recorded on top of them"
            case "run":
                if self.blocker is None:
                    return "the run this command starts uses them"
                return f"run {self.blocker} ran with them"
            case "committed":
                return "they're committed, and nothing in git is rewritten"
            case "shares-segment":
                return "their event file holds other events too"


def round_trip(history: Sequence[RecordedEvent], closing: str) -> RoundTrip | None:
    """The round trip the sweep whose change id is ``closing`` closed, or None (design D1, D2).
    ``history`` is the config stream's every event, as the store orders them."""
    tail, base = _tail(history)
    edits = [n for n, r in enumerate(tail) if _is_sweep(r, closing)]
    if not edits:
        return None
    states: list[Tree] = [base]
    for record in tail:
        states.append(apply(states[-1], _entries(record)))
    starts: list[int] = []
    ends: list[int] = []
    scopes: list[_Scope] = []
    files: list[str] = []
    for y in edits:
        scope = _scope_of(tail[y])
        if scope is None:
            continue
        after = scope.value(states[y + 1])
        x = next((i for i in range(y - 1, -1, -1) if scope.value(states[i]) == after), None)
        if x is None:
            continue
        starts.append(x)
        ends.append(y)
        scopes.append(scope)
        files.append(_file_of(tail[y]))
    if not starts:
        return None
    trip = tail[min(starts) : max(ends) + 1]
    changes: list[str] = []
    outside: str | None = None
    for record in trip:
        change = _change_of(record)
        if change not in changes:
            changes.append(change)
        if outside is None and any(not _inside(tuple(e["path"]), scopes) for e in _entries(record)):
            outside = change
    return RoundTrip(closing, tuple(r.id for r in trip), tuple(changes), tuple(files), outside)


def head_sweep(history: Sequence[RecordedEvent]) -> str | None:
    """The change id of the sweep whose last edit is the config stream's head, or None: the one
    round trip a sync may ask about again (design D5)."""
    tail, _ = _tail(history)
    if not tail:
        return None
    head = tail[-1]
    lineage = head.lineage or {}
    if lineage.get("via") != "file" or lineage.get("actor", {}).get("kind") != "unknown":
        return None
    change = lineage.get("change")
    return change if isinstance(change, str) else None


def blocked(store: EventStore, trip: RoundTrip, *, runs_now: bool = False) -> Blocked | None:
    """Why ``trip`` can't be dropped, the first of design D3's reasons that holds, or None."""
    if trip.outside is not None:
        return Blocked("changes-more", trip.outside)
    return _referred(store, trip, runs_now=runs_now) or _segments(store, trip)


def referred(store: EventStore, trip: RoundTrip) -> Blocked | None:
    """D3's ``built-on`` and ``run``, on a fresh read: what a drop re-checks holding the store's
    lock, so no run can start in between."""
    return _referred(store, trip, runs_now=False)


def _referred(store: EventStore, trip: RoundTrip, *, runs_now: bool) -> Blocked | None:
    ours = set(trip.events)
    for record in store.history(aggregate.STREAM):
        if record.id not in ours and ours.intersection(record.parents):
            return Blocked("built-on", _change_of(record))
    run = _run_using(store, ours)
    if run is not None:
        return Blocked("run", run)
    if runs_now:
        return Blocked("run")
    return None


def _segments(store: EventStore, trip: RoundTrip) -> Blocked | None:
    reason = store.recorder.droppable(trip.events)
    if reason == "committed":
        return Blocked("committed")
    if reason == "shares-segment":
        return Blocked("shares-segment")
    return None


_PAGE = 500


def _run_using(store: EventStore, events: set[str]) -> str | None:
    """The id of a run whose config version names one of ``events``, or None."""
    from troupe.core.runs.aggregate import STARTED

    low = 1
    while True:
        page = store.recorder.notifications(low, _PAGE, None, [STARTED])
        for _, record in page:
            state = strict_json.loads(record.state)
            if isinstance(state, dict) and events.intersection(state.get("config", ())):
                return str(state.get("run_id", record.stream))
        if len(page) < _PAGE:
            return None
        low = page[-1][0] + 1


def _tail(history: Sequence[RecordedEvent]) -> tuple[list[RecordedEvent], Tree]:
    """The chain from the stream's head back to just after its last settle (or its start), in
    order, and config as the events before it leave it (design D2). Empty while forked."""
    by_id = {r.id: r for r in history}
    children = {p for r in history for p in r.parents}
    heads = [r for r in history if r.id not in children]
    if len(heads) != 1:
        return [], {}
    chain: list[RecordedEvent] = []
    current: RecordedEvent | None = heads[0]
    while current is not None and current.topic == aggregate.CHANGED:
        chain.append(current)
        if len(current.parents) != 1:
            break
        current = by_id.get(current.parents[0])
    chain.reverse()
    ours = {r.id for r in chain}
    before = [r for r in history if r.id not in ours]
    return chain, merge(before).config if before else {}


def _entries(record: RecordedEvent) -> list[dict[str, Any]]:
    state = strict_json.loads(record.state)
    found = state.get("changes", []) if isinstance(state, dict) else []
    return list(found)


def _files(record: RecordedEvent) -> list[dict[str, Any]]:
    state = strict_json.loads(record.state)
    return list(state.get("files", [])) if isinstance(state, dict) else []


def _change_of(record: RecordedEvent) -> str:
    return str((record.lineage or {}).get("change", ""))


def _is_sweep(record: RecordedEvent, closing: str) -> bool:
    lineage = record.lineage or {}
    return (
        lineage.get("change") == closing
        and lineage.get("via") == "file"
        and lineage.get("actor", {}).get("kind") == "unknown"
    )


def _file_of(record: RecordedEvent) -> str:
    return str(_files(record)[0]["path"])


def _scope_of(record: RecordedEvent) -> _Scope | None:
    """The part of config the file a hand edit names owns; an actor's whole group when the edit
    removed both its files (design D1)."""
    files = _files(record)
    if not files:
        return None
    located = owner(str(files[0]["path"]))
    if located is None:
        return None
    group, holds = located
    if holds == "character":
        return _Scope(group, "character")
    if group[0] != ACTORS:
        return _Scope(group, "whole")
    removes_group = any(tuple(e["path"]) == group and "after" not in e for e in _entries(record))
    return _Scope(group, "whole" if removes_group else "fields")


def _inside(path: Point, scopes: Sequence[_Scope]) -> bool:
    """Whether a change at ``path`` stays within the parts ``scopes`` own."""
    parts = {(s.group, s.part) for s in scopes}
    for scope in scopes:
        group = scope.group
        if path[: len(group)] != group:
            continue
        if scope.part == "whole":
            return True
        if len(path) == len(group):
            # The whole group: inside only when both its parts are.
            if {(group, "fields"), (group, "character")} <= parts:
                return True
            continue
        is_character = path[len(group)] == CHARACTER
        if (scope.part == "character") == is_character:
            return True
    return False


# The record of the round trips a person kept (design D7).

KEPT = "local/config/kept.json"
"""This clone's record of the round trips a person kept: the closing change ids. Out of git, like
everything under local/, since it's about this clone's uncommitted events."""


def kept(troupe_dir: Path) -> tuple[frozenset[str], list[Notice]]:
    """The closing change ids a person kept; none when there's no record, and none, with a
    ``config.kept-unreadable`` notice, when it can't be read (design D7)."""
    path = troupe_dir / KEPT
    if not path.is_file():
        return frozenset(), []
    try:
        found = strict_json.loads(path.read_bytes())
        if not isinstance(found, list) or not all(isinstance(c, str) for c in found):
            raise strict_json.StrictJSONError("not a list of change ids")
    except (strict_json.StrictJSONError, OSError) as error:
        return frozenset(), [
            Notice(
                "config.kept-unreadable",
                problem=f"troupe's record of the abandoned edits you kept can't be read ({error}), "
                "so it may ask about one you kept.",
                fix="Run troupe config keep again for any it asks about; that writes the record "
                "again.",
                path=str(path),
            )
        ]
    return frozenset(found), []


def write_kept(troupe_dir: Path, changes: frozenset[str], present: frozenset[str]) -> None:
    """Record ``changes`` as kept, leaving out any whose change isn't in the stream any more
    (``present``), so the record doesn't grow."""
    from troupe.core.files import replace_file

    target = troupe_dir / KEPT
    target.parent.mkdir(parents=True, exist_ok=True)
    listed = sorted(c for c in changes if c in present)
    replace_file(target, strict_json.dumps(listed).encode("utf-8") + b"\n")


# Reporting (design D5).


def report(
    store: EventStore,
    troupe_dir: Path,
    closing: str | None,
    *,
    runs_now: bool = False,
    only_droppable: bool = False,
) -> list[Notice]:
    """``config.edit-abandoned`` for the round trip the sweep ``closing`` closed, unless there's
    none or the person kept it; with ``only_droppable``, only while it can still be dropped."""
    if closing is None:
        return []
    trip = round_trip(store.history(aggregate.STREAM), closing)
    if trip is None:
        return []
    held, notices = kept(troupe_dir)
    if closing in held:
        return notices
    block = blocked(store, trip, runs_now=runs_now)
    if only_droppable and block is not None:
        return notices
    return [*notices, abandoned_notice(trip, block, troupe_dir)]


def remind(store: EventStore, troupe_dir: Path, reported: str | None) -> list[Notice]:
    """troupe sync's reminder (owner, Q4): the round trip at the head of the config stream, again,
    while it can still be dropped and the person hasn't kept it. ``reported`` is the sweep this
    sync recorded, whose round trip, if any, it has already reported."""
    closing = head_sweep(store.history(aggregate.STREAM))
    if closing is None or closing == reported:
        return []
    return report(store, troupe_dir, closing, only_droppable=True)


def abandoned_notice(trip: RoundTrip, block: Blocked | None, troupe_dir: Path) -> Notice:
    files = [f"{THEATRE_DIR}/{path}" for path in trip.files]
    count = len(trip.changes)
    back = "is back to what it was" if len(files) == 1 else "are back to what they were"
    details: dict[str, Any] = {
        "change": trip.closing,
        "files": files,
        "changes": list(trip.changes),
        "droppable": block is None,
    }
    if block is None:
        outcome = "can be dropped"
        fix = (
            f"troupe config drop {trip.closing} removes them; troupe config keep {trip.closing} "
            "keeps them and stops this notice."
        )
    else:
        outcome = f"are kept, because {block.describe()}"
        fix = "Nothing to do: they stay in history."
        details["reason"] = block.reason
        if block.blocker is not None:
            details["blocker"] = block.blocker
    return Notice(
        "config.edit-abandoned",
        problem=f"{', '.join(files)} {back} before change {trip.changes[0]}: the {count} changes "
        f"since {outcome}.",
        fix=fix,
        path=str(troupe_dir / trip.files[0]),
        details=details,
    )
