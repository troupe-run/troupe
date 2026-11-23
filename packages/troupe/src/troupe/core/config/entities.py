"""Which entity each config write names, through renames (spec: config, "A change on another line
follows a rename", "A name after a rename is a new entity", "Renames that can't both hold are a
conflict"; config-mv design D2, D3).

The merge (``troupe.core.config.merge``) contests and replays writes by path. A rename moves a
whole actor or runtime to a new name, so before it contests anything, it asks this module which
entity each write names, and writes the path as ``(kind, key, rest...)``:

- **A key** is the name the entity was born with, plus, when renames in the writing event's history
  had freed that name (renamed something away from it), those renames' ids. With no renames, a
  key is its name, so paths are what they were and the merge is unchanged.
- **A view** maps each name an event sees to its key: with one parent, the parent's view after its
  own entries; at a join (a settle, or the merge's ``extra`` change), worked out from the join's
  whole history by the name contest below.
- **An event's entries are read against its view.** A write under a name the view doesn't map
  is a birth; a rename moves the old name's key to the new name; a group's removal is its key's
  removal.

**The name contest.** Each key's births, renames and removals are contested by the merge's rule
for values: latest writes, each line's net change, a line that ends where it began drops out, and
lines left that differ conflict whole, with the history before them deciding the name. A
conflict with a rename among its conflicting writes is reported (two renames, or a rename and a
removal); one without a rename is never reported, since values already contest births and
removals. A removal on the losing side of a reported conflict is left out of replay too.

**Clashes.** Two keys whose names come out the same: when one key's claim to the name (the write
that gave it the name) follows the other's, the later one has it (on one line, a name can only be
taken when nothing's there). When they're concurrent, the renames that claimed it are left out, so
those keys fall back to their earlier names, and the clash is reported. A fallback that clashes
again leaves its key out of config while the conflict stands.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from troupe.core.config.changes import RENAMED_FROM, Tree
from troupe.core.config.kinds import KINDS

Key = tuple[str, str]
"""An entity: its kind, and its key's token."""
Id = tuple[str, int]
"""An entry: its event, and its index in the event."""
Point = tuple[str, ...]
_FREED = "\x00"
"""Joins a key's name and the renames that freed it: never in a name, so a token with it is never
mistaken for one."""


@dataclass(frozen=True)
class NameWrite:
    """One entry's effect on a key's name: a birth (``before`` None), a rename, or a removal
    (``after`` None)."""

    event: str
    index: int
    key: Key
    before: str | None
    after: str | None
    rename: bool

    @property
    def id(self) -> Id:
        return (self.event, self.index)


@dataclass
class Named:
    """Every key's name over a set of events, and what the name contest found."""

    states: dict[Key, str | None]
    last: dict[Key, str]
    """For a key whose name came out removed but that still holds values (removed on one line,
    written on another): its name worked out by the contest from its births and renames alone, so
    it's the same in every order."""
    hidden: set[Key]
    """Keys left out of config: displaced by a later claim on one line, or clashing again after
    falling back."""
    conflicts: list[tuple[tuple[Point, ...], list[str]]]
    """Each reported conflict: its paths (as shown) and the events in it."""
    removals_left_out: set[Id]
    view: dict[tuple[str, str], str] = field(default_factory=dict)
    clashed: bool = False
    """Whether two keys came out with one name: a view carried along a line from here can go
    stale (a removal of one side can let the other's rename have the name), so the events after
    it work their views out from their history instead."""

    def name(self, key: Key) -> str:
        """The name ``key`` is shown under."""
        state = self.states.get(key)
        if isinstance(state, str):
            return state
        return self.last.get(key, key[1].split(_FREED)[0])

    def path(self, path: Sequence[str]) -> Point:
        """``path``, an entity path, as shown: its key replaced by its name."""
        if len(path) >= 2 and path[0] in KINDS:
            return (path[0], self.name((path[0], path[1])), *path[2:])
        return tuple(path)

    def shown(self, keyed: Mapping[str, Any]) -> Tree:
        """``keyed``, config replayed on entity paths, with each entity under its name."""
        config: Tree = {}
        for top, node in keyed.items():
            if top not in KINDS or not isinstance(node, Mapping):
                config[top] = node
                continue
            out: dict[str, Any] = {}
            for token in sorted(node):
                key = (top, token)
                name = self.name(key)
                if key in self.hidden or name in out:
                    continue
                out[name] = node[token]
            if out:
                config[top] = out
        return config


@dataclass
class _Clash:
    """What settling clashes has done so far: keys that fell back, and names reported."""

    fell_back: set[Key]
    reported: set[tuple[str, str]]


@dataclass
class Entities:
    """Every write's entity path, and every key's name writes, for one history."""

    ancestors: Mapping[str, frozenset[str]]
    paths: dict[Id, Point] = field(default_factory=dict)
    writes: dict[Key, list[NameWrite]] = field(default_factory=dict)
    views: dict[str, dict[tuple[str, str], str]] = field(default_factory=dict)
    """Each event's view after its own entries."""
    renames_from: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    """The events that renamed something away from each name."""

    def named(self, events: Iterable[str]) -> Named:
        """The name contest over ``events`` (a set closed under ancestry)."""
        within = set(events)
        dropped: set[Id] = set()
        conflicts: list[tuple[tuple[Point, ...], list[str]]] = []
        reported: list[Key] = []
        conflicting_events: dict[Key, list[str]] = {}
        removals: set[Id] = set()
        for key, all_writes in self.writes.items():
            writes = [w for w in all_writes if w.event in within]
            found = _contest(writes, self.ancestors)
            if found is None:
                continue
            drop, conflicting = found
            dropped |= drop
            if conflicting and any(w.rename for w in conflicting):
                reported.append(key)
                conflicting_events[key] = sorted({w.event for w in conflicting})
                removals |= {w.id for w in writes if w.id in drop and w.after is None}
        states, _, claims = self._replay(within, dropped)
        named = Named(states, self._without_removals(within), set(), conflicts, removals)
        for key in reported:
            conflicts.append((((key[0], named.name(key)),), conflicting_events[key]))
        self._clashes(named, within, dropped, claims)
        named.view = {
            (key[0], state): key[1]
            for key, state in named.states.items()
            if isinstance(state, str) and key not in named.hidden
        }
        return named

    def _replay(
        self, within: set[str], dropped: set[Id]
    ) -> tuple[dict[Key, str | None], dict[Key, str], dict[Key, list[NameWrite]]]:
        """Each key's name, the last name it had, and its claims: the latest writes that gave it
        the name it has (several when concurrent lines agree)."""
        states: dict[Key, str | None] = {}
        last: dict[Key, str] = {}
        claims: dict[Key, list[NameWrite]] = {}
        for key, writes in self.writes.items():
            applied = [w for w in writes if w.event in within and w.id not in dropped]
            for write in applied:
                states[key] = write.after
                name = write.after if write.after is not None else write.before
                if name is not None:
                    last[key] = name
            state = states.get(key)
            if state is None:
                continue
            giving = [w for w in applied if w.after == state]
            claims[key] = [
                w
                for w in giving
                if not any(w.event in self.ancestors[o.event] for o in giving if o is not w)
            ]
        return states, last, claims

    def _clashes(
        self,
        named: Named,
        within: set[str],
        dropped: set[Id],
        claims: dict[Key, list[NameWrite]],
    ) -> None:
        """Settle keys whose names come out the same (see the module's docstring)."""
        clash = _Clash(fell_back=set(), reported=set())
        for _ in range(len(self.writes) + 1):
            by_name: dict[tuple[str, str], list[Key]] = {}
            for key, state in named.states.items():
                if isinstance(state, str) and key not in named.hidden:
                    by_name.setdefault((key[0], state), []).append(key)
            changed = False
            for name, keys in sorted(by_name.items()):
                if len(keys) > 1:
                    named.clashed = True
                    changed = self._settle(named, name, keys, claims, dropped, clash) or changed
            if not changed:
                return
            named.states, _, new_claims = self._replay(within, dropped)
            claims.clear()
            claims.update(new_claims)

    def _settle(
        self,
        named: Named,
        name: tuple[str, str],
        keys: list[Key],
        claims: dict[Key, list[NameWrite]],
        dropped: set[Id],
        clash: "_Clash",
    ) -> bool:
        """Settle one name that ``keys`` came out with; whether any name changed."""
        later = [
            k for k in keys if all(self._follows(claims[k], claims[o]) for o in keys if o != k)
        ]
        if later:
            named.hidden |= set(keys) - set(later)
            return False
        again = [k for k in keys if k in clash.fell_back]
        if again:
            named.hidden |= set(again)
            return True
        if name not in clash.reported:
            clash.reported.add(name)
            named.conflicts.append(((name,), sorted({c.event for k in keys for c in claims[k]})))
        renamed = [k for k in keys if any(c.rename for c in claims[k])]
        if not renamed:
            named.hidden |= set(sorted(keys)[1:])
            return True
        dropped |= {c.id for k in renamed for c in claims[k] if c.rename}
        clash.fell_back |= set(renamed)
        return True

    def _without_removals(self, within: set[str]) -> dict[Key, str]:
        """Each key's name from its births and renames alone, contested as the name is."""
        found: dict[Key, str] = {}
        for key, all_writes in self.writes.items():
            writes = [w for w in all_writes if w.event in within and w.after is not None]
            contested = _contest(writes, self.ancestors)
            drop = contested[0] if contested is not None else set()
            for write in writes:
                if write.id not in drop and write.after is not None:
                    found[key] = write.after
        return found

    def _follows(self, mine: Sequence[NameWrite], theirs: Sequence[NameWrite]) -> bool:
        """Whether one of ``mine`` follows every one of ``theirs``: a later claim on one line."""
        return any(all(o.event in self.ancestors[c.event] for o in theirs) for c in mine)


def entities(
    order: Sequence[str],
    parents: Mapping[str, Sequence[str]],
    ancestors: Mapping[str, frozenset[str]],
    entries: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Entities:
    """Every write's entity, for the events in ``order`` (parents first), whose entries are
    ``entries`` (an event with none, such as a settle, is left out of it)."""
    found = Entities(ancestors)
    clashed: set[str] = set()
    for event in order:
        mine = parents.get(event, ())
        if not mine:
            view: dict[tuple[str, str], str] = {}
        elif len(mine) == 1 and mine[0] not in clashed:
            view = dict(found.views[mine[0]])
        else:
            named = found.named(ancestors[event])
            view = dict(named.view)
            if named.clashed:
                clashed.add(event)
        for index, entry in enumerate(entries.get(event, ())):
            _read(found, event, index, entry, view)
        found.views[event] = view
    return found


def _read(
    found: Entities,
    event: str,
    index: int,
    entry: Mapping[str, Any],
    view: dict[tuple[str, str], str],
) -> None:
    """Read one entry against ``view``, updating it: its entity path, and its name write."""
    path = tuple(entry["path"])
    if not path or path[0] not in KINDS:
        found.paths[(event, index)] = path
        return
    kind = path[0]
    if len(path) == 1:
        found.paths[(event, index)] = path
        for (k, name), token in list(view.items()):
            if k == kind:
                if "after" not in entry:
                    _write(found, event, index, (kind, token), name, None, rename=False)
                del view[(k, name)]
        return
    name = path[1]
    if RENAMED_FROM in entry:
        old = str(entry[RENAMED_FROM][1])
        held = view.pop((kind, old), None)
        token = held if held is not None else _token(found, event, kind, old)
        _write(found, event, index, (kind, token), old, name, rename=True)
        view[(kind, name)] = token
        found.renames_from.setdefault((kind, old), []).append(event)
        found.paths[(event, index)] = (kind, token)
        return
    mapped = view.get((kind, name))
    if mapped is None:
        token = _token(found, event, kind, name)
        if "after" in entry:
            _write(found, event, index, (kind, token), None, name, rename=False)
            view[(kind, name)] = token
    else:
        token = mapped
        if len(path) == 2 and "after" not in entry:
            _write(found, event, index, (kind, token), name, None, rename=False)
            del view[(kind, name)]
    found.paths[(event, index)] = (kind, token, *path[2:])


def _token(found: Entities, event: str, kind: str, name: str) -> str:
    """The key a write under ``name`` the view doesn't map names: the name, plus the renames in
    the event's history that freed it."""
    freed = sorted(
        e for e in found.renames_from.get((kind, name), ()) if e in found.ancestors[event]
    )
    return _FREED.join([name, *freed]) if freed else name


def _write(
    found: Entities,
    event: str,
    index: int,
    key: Key,
    before: str | None,
    after: str | None,
    *,
    rename: bool,
) -> None:
    found.writes.setdefault(key, []).append(NameWrite(event, index, key, before, after, rename))


def _contest(
    writes: Sequence[NameWrite], ancestors: Mapping[str, frozenset[str]]
) -> tuple[set[Id], list[NameWrite]] | None:
    """A key's name contest: the writes to leave out, and the latest writes in conflict. As the
    merge's value contest, rounds go on beneath while no latest write stays in (#190)."""
    found = _round(writes, ancestors)
    if found is None:
        return None
    drop, conflicting, latest = found
    while not {w.id for w in latest} - drop:
        left = [w for w in writes if w.id not in drop]
        beneath = _round(left, ancestors)
        if beneath is None:
            break
        drop |= beneath[0]
        latest = beneath[2]
    return drop, conflicting


def _round(
    writes: Sequence[NameWrite], ancestors: Mapping[str, frozenset[str]]
) -> tuple[set[Id], list[NameWrite], list[NameWrite]] | None:
    latest_by_event: dict[str, NameWrite] = {}
    for write in writes:
        if any(write.event in ancestors[o.event] for o in writes):
            continue
        current = latest_by_event.get(write.event)
        if current is None or write.index >= current.index:
            latest_by_event[write.event] = write
    if len(latest_by_event) <= 1:
        return None
    latest = list(latest_by_event.values())
    lines: dict[str, list[NameWrite]] = {}
    for write in latest:
        others = set().union(*({o.event} | ancestors[o.event] for o in latest if o is not write))
        mine = ancestors[write.event] | {write.event}
        lines[write.event] = [w for w in writes if w.event in mine and w.event not in others]
    drop: set[Id] = set()
    left: list[NameWrite] = []
    for write in latest:
        line = lines[write.event]
        last = line[-1]
        firsts = [w for w in line if not any(o.event in ancestors[w.event] for o in line)]
        if all(w.before == last.after for w in firsts):
            drop |= {w.id for w in line}
        else:
            left.append(write)
    if len({w.after for w in left}) <= 1:
        return drop, [], latest
    for write in latest:
        drop |= {w.id for w in lines[write.event]}
    return drop, left, latest


@dataclass(frozen=True)
class Names:
    """Which entity a name meant at a config version, and its name now (config-mv design D4)."""

    found: Entities
    named: Named
    events: frozenset[str]
    present: frozenset[Key]
    """The keys that hold values in config now."""

    def current(self, kind: str, name: str, heads: Sequence[str]) -> str | None:
        """What the entity ``name`` meant at ``heads`` is called now: None when it holds nothing
        now, or ``heads`` aren't all in the stream."""
        if not heads or any(head not in self.events for head in heads):
            return None
        at: set[str] = set()
        for head in heads:
            at |= self.found.ancestors[head] | {head}
        token = self.found.named(at).view.get((kind, name))
        if token is None or (kind, token) not in self.present:
            return None
        return self.named.name((kind, token))
