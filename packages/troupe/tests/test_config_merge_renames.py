"""The config merge with renames, over generated histories (spec: config, "A change on another line
follows a rename", "Renames that can't both hold are a conflict"; config-mv design D2, D3).

The histories are built in memory, as in test_config_merge_properties.py, with more kinds of
change: actors made, removed and renamed, as well as values changed, on lines that fork and settle.
Three properties:

- **No rename, no difference.** For a history with no rename, the merge works out exactly the
  config and conflicts the merge as it was before renames (``merge_oracle``) does.
- **Order doesn't matter.** Every order the events can arrive in works out the same config and
  conflicts, renames and all.
- **A rename and its reverse change nothing.** Renaming an actor and renaming it back, at the tip
  of a line, leaves config as it was.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

import merge_oracle
from troupe.core.config import aggregate
from troupe.core.config.changes import UNSET, Rename, Tree, apply, change
from troupe.core.config.merge import Merged, merge

TESTER: dict[str, Any] = {
    "runner": "scripted",
    "options": {"script": {"steps": [{"exit": 0}]}},
    "expect": [],
}
NAMES = ("tester", "reviewer", "qa")
FIELDS = ("character", "expect")
VALUES: dict[str, list[Any]] = {"character": ["A", "B", "C"], "expect": [[], ["a.txt"], ["b.txt"]]}


@dataclass(frozen=True)
class Record:
    """A recorded event, as the store returns it."""

    id: str
    parents: tuple[str, ...]
    topic: str
    state: bytes
    version: int
    stream: str = str(aggregate.STREAM)
    path: Path = Path("segment.jsonl")
    line: int = 1
    lineage: dict[str, Any] | None = field(default=None)


def _id(seed: object) -> str:
    return "sha256:" + hashlib.sha256(repr(seed).encode()).hexdigest()


def _changed(n: int, parents: Sequence[str], entries: list[dict[str, Any]]) -> Record:
    state = json.dumps({"changes": entries, "files": []}).encode()
    lineage = {"change": f"{n:026d}", "actor": {"kind": "unknown"}, "at": f"t{n}"}
    return Record(_id(("change", n)), tuple(parents), aggregate.CHANGED, state, n, lineage=lineage)


def _settled(n: int, parents: Sequence[str]) -> Record:
    return Record(_id(("settle", n)), tuple(sorted(parents)), aggregate.SETTLED, b"{}", n)


def _base() -> list[Record]:
    entries = change({}, [(("actors", name), dict(TESTER)) for name in NAMES[:2]])
    return [_changed(1, [], entries)]


def _ancestry(records: Sequence[Record], tip: str) -> list[Record]:
    by_id = {r.id: r for r in records}
    wanted: set[str] = set()
    stack = [tip]
    while stack:
        event = stack.pop()
        if event not in wanted:
            wanted.add(event)
            stack.extend(by_id[event].parents)
    return [r for r in records if r.id in wanted]


def _operation(draw: st.DrawFn, state: Tree, renames: bool) -> list[tuple[Any, object]] | None:
    """One command's operations on ``state``: a value set, an actor made or removed, or (with
    ``renames``) an actor renamed to a name config doesn't hold."""
    actors = state.get("actors", {})
    kinds = ["set", "set", "make", "remove"] + (["rename", "rename"] if renames else [])
    kind = draw(st.sampled_from(kinds))
    held = sorted(actors)
    free = [name for name in NAMES if name not in actors]
    if kind == "set" and held:
        name = draw(st.sampled_from(held))
        field_ = draw(st.sampled_from(FIELDS))
        return [(("actors", name, field_), draw(st.sampled_from(VALUES[field_])))]
    if kind == "make" and free:
        return [(("actors", draw(st.sampled_from(free))), dict(TESTER))]
    if kind == "remove" and held:
        return [(("actors", draw(st.sampled_from(held))), UNSET)]
    if kind == "rename" and held and free:
        source = draw(st.sampled_from(held))
        return [(("actors", draw(st.sampled_from(free))), Rename(("actors", source)))]
    return None


@st.composite
def histories(draw: st.DrawFn, renames: bool = True) -> list[Record]:
    """Lines that change values, make, remove and rename actors, fork and settle each other, in
    creation order."""
    records = _base()
    tips = [records[0].id]
    for n in range(2, draw(st.integers(4, 14)) + 2):
        action = draw(st.sampled_from(["change", "change", "fork", "settle"]))
        if action == "fork" or (len(tips) == 1 and action == "settle"):
            tips.append(draw(st.sampled_from(tips)))
            continue
        if action == "settle":
            distinct = sorted(set(tips))
            if len(distinct) < 2:
                continue
            pair = draw(st.lists(st.sampled_from(distinct), min_size=2, max_size=2, unique=True))
            one, other = ({r.id for r in _ancestry(records, tip)} for tip in pair)
            if pair[0] in other or pair[1] in one:
                continue  # one descends from the other: there's no fork to settle
            record = _settled(n, pair)
            records.append(record)
            tips = [t for t in tips if t not in pair] + [record.id]
            continue
        index = draw(st.integers(0, len(tips) - 1))
        state = merge(_ancestry(records, tips[index])).config
        operations = _operation(draw, state, renames)
        if operations is None:
            continue
        entries = change(state, operations)
        if not entries:
            continue
        record = _changed(n, [tips[index]], entries)
        records.append(record)
        tips[index] = record.id
    return records


def _orders(data: st.DataObject, records: Sequence[Record]) -> list[Record]:
    """``records`` in another order that keeps every parent before its children."""
    pending = list(records)
    placed: set[str] = set()
    order: list[Record] = []
    while pending:
        ready = [r for r in pending if all(p in placed for p in r.parents)]
        record = data.draw(st.sampled_from(ready))
        order.append(record)
        placed.add(record.id)
        pending.remove(record)
    return order


def _summary(merged: Merged | merge_oracle.Merged) -> tuple[object, ...]:
    return (
        json.dumps(merged.config, sort_keys=True),
        sorted((c.paths, sorted(x.id for x in c.changes), c.rule) for c in merged.conflicts),
        merged.heads,
    )


# Requirement: A change on another line follows a rename ("A history with no renames")


@settings(max_examples=500)
@given(histories(renames=False))
def test_a_history_with_no_rename_merges_exactly_as_the_merge_before_renames(
    records: list[Record],
) -> None:
    assert _summary(merge(records)) == _summary(merge_oracle.merge(records))


# Requirement: A change on another line follows a rename ("Every clone agrees on a rename")


@settings(max_examples=500)
@given(st.data())
def test_every_order_the_events_can_arrive_in_works_out_the_same_config_with_renames(
    data: st.DataObject,
) -> None:
    records = data.draw(histories())
    first = _summary(merge(records))
    for _ in range(3):
        again = _orders(data, records)
        assert _summary(merge(again)) == first


@settings(max_examples=300)
@given(st.data())
def test_a_rename_and_its_reverse_at_a_lines_tip_leave_config_as_it_was(
    data: st.DataObject,
) -> None:
    records = data.draw(histories())
    tip = records[-1]
    before = merge(_ancestry(records, tip.id))
    actors = sorted(before.config.get("actors", {}))
    free = [name for name in NAMES if name not in before.config.get("actors", {})]
    if before.conflicts or not actors or not free:
        return
    source = data.draw(st.sampled_from(actors))
    target = data.draw(st.sampled_from(free))
    there = change(before.config, [(("actors", target), Rename(("actors", source)))])
    moved = _changed(100, [tip.id], there)
    back = change(apply(before.config, there), [(("actors", source), Rename(("actors", target)))])
    returned = _changed(101, [moved.id], back)
    after = merge([*_ancestry(records, tip.id), moved, returned])
    assert after.config == before.config
    assert after.conflicts == ()


# Examples, one per scenario


def _step(records: list[Record], n: int, parent: str, operations: list[tuple[Any, object]]) -> str:
    """Record version ``n`` after ``parent``: ``operations`` worked out from its history."""
    state = merge(_ancestry(records, parent)).config
    record = _changed(n, [parent], change(state, operations))
    records.append(record)
    return record.id


def _two_lines(
    left: list[list[tuple[Any, object]]], right: list[list[tuple[Any, object]]]
) -> list[Record]:
    """A base (tester and reviewer), then two lines off it, each a list of commands."""
    records = _base()
    n = 2
    for line in (left, right):
        tip = records[0].id
        for operations in line:
            tip = _step(records, n, tip, operations)
            n += 1
    return records


def _rename(old: str, new: str) -> list[tuple[Any, object]]:
    return [(("actors", new), Rename(("actors", old)))]


def _every_order(records: Sequence[Record]) -> list[list[Record]]:
    """Every order of ``records`` that keeps each parent before its children."""
    if not records:
        return [[]]
    placed = {r.id for r in records}
    ready = [r for r in records if not placed & set(r.parents)]
    return [
        [record, *rest]
        for record in ready
        for rest in _every_order([r for r in records if r is not record])
    ]


def _in_every_order(records: list[Record]) -> Merged:
    """The merge of ``records``, checked to be the same in every order they can arrive in."""
    first = merge(records)
    for order in _every_order(records):
        assert _summary(merge(order)) == _summary(first)
    return first


CHARACTER: list[tuple[Any, object]] = [(("actors", "tester", "character"), "A")]


def test_a_character_set_on_a_branch_that_didnt_rename_lands_on_the_new_name() -> None:
    merged = _in_every_order(_two_lines([_rename("tester", "qa")], [CHARACTER]))
    assert merged.config["actors"]["qa"] == {**TESTER, "character": "A"}
    assert "tester" not in merged.config["actors"]
    assert merged.conflicts == ()


def test_a_rename_and_a_rename_back_leave_another_lines_change_on_the_old_name() -> None:
    runner: list[tuple[Any, object]] = [(("actors", "tester", "runner"), "other")]
    merged = _in_every_order(
        _two_lines([_rename("tester", "qa"), _rename("qa", "tester")], [runner])
    )
    assert merged.config["actors"]["tester"]["runner"] == "other"
    assert "qa" not in merged.config["actors"]
    assert merged.conflicts == ()


def test_a_name_set_after_a_rename_on_the_same_line_is_a_new_actor() -> None:
    records = _base()
    renamed = _step(records, 2, records[0].id, _rename("tester", "qa"))
    _step(records, 3, renamed, [(("actors", "tester"), {"runner": "scripted", "expect": []})])
    merged = merge(records)
    assert merged.config["actors"]["qa"] == TESTER
    assert merged.config["actors"]["tester"] == {"runner": "scripted", "expect": []}


def test_a_concurrent_change_follows_the_rename_not_the_new_actor_of_the_old_name() -> None:
    new_tester: list[tuple[Any, object]] = [
        (("actors", "tester"), {"runner": "scripted", "expect": []})
    ]
    merged = _in_every_order(_two_lines([_rename("tester", "qa"), new_tester], [CHARACTER]))
    assert merged.config["actors"]["qa"]["character"] == "A"
    assert merged.config["actors"]["tester"] == {"runner": "scripted", "expect": []}
    assert merged.conflicts == ()


def test_two_renames_of_one_actor_conflict_and_show_it_under_its_name_from_before() -> None:
    merged = _in_every_order(_two_lines([_rename("tester", "qa")], [_rename("tester", "checker")]))
    assert [c.paths for c in merged.conflicts] == [(("actors", "tester"),)]
    assert len(merged.conflicts[0].changes) == 2
    assert merged.config["actors"]["tester"] == TESTER
    assert {"qa", "checker"}.isdisjoint(merged.config["actors"])


def test_the_same_rename_on_two_branches_agrees() -> None:
    merged = _in_every_order(_two_lines([_rename("tester", "qa")], [_rename("tester", "qa")]))
    assert merged.config["actors"]["qa"] == TESTER
    assert merged.conflicts == ()


def test_a_rename_and_a_removal_conflict_and_leave_the_actor_as_it_was() -> None:
    removal: list[tuple[Any, object]] = [(("actors", "tester"), UNSET)]
    merged = _in_every_order(_two_lines([_rename("tester", "qa")], [removal]))
    assert [c.paths for c in merged.conflicts] == [(("actors", "tester"),)]
    assert merged.config["actors"]["tester"] == TESTER


def test_a_rename_onto_a_name_another_branch_made_conflicts_on_that_name() -> None:
    made: list[tuple[Any, object]] = [(("actors", "qa"), {"runner": "scripted", "expect": []})]
    merged = _in_every_order(_two_lines([_rename("tester", "qa")], [made]))
    assert [c.paths for c in merged.conflicts] == [(("actors", "qa"),)]
    assert len(merged.conflicts[0].changes) == 2
    assert merged.config["actors"]["tester"] == TESTER
    assert merged.config["actors"]["qa"] == {"runner": "scripted", "expect": []}


def test_a_rename_after_the_merge_resolves_two_renames() -> None:
    records = _two_lines([_rename("tester", "qa")], [_rename("tester", "checker")])
    heads = merge(records).heads
    resolution = change(merge(records).config, _rename("tester", "qa"))
    from troupe.core.config.merge import Change

    proposed = Change("proposed", "", {}, "", tuple(resolution), ())
    merged = merge(records, extra=proposed)
    assert merged.conflicts == ()
    assert merged.config["actors"]["qa"] == TESTER
    assert "tester" not in merged.config["actors"]
    assert len(heads) == 2


def test_a_removal_after_the_merge_resolves_a_rename_onto_a_name_another_branch_made() -> None:
    made: list[tuple[Any, object]] = [(("actors", "qa"), {"runner": "scripted", "expect": []})]
    records = _two_lines([_rename("tester", "qa")], [made])
    from troupe.core.config.merge import Change

    removal = change(merge(records).config, [(("actors", "qa"), UNSET)])
    merged = merge(records, extra=Change("proposed", "", {}, "", tuple(removal), ()))
    assert merged.conflicts == ()
    assert merged.config["actors"]["qa"] == TESTER
    assert "tester" not in merged.config["actors"]


# Merged.names: what a name meant at a config version is called now (design D4)


def test_a_name_at_an_earlier_version_follows_a_chain_of_renames_to_its_name_now() -> None:
    records = _base()
    first = records[0].id
    renamed = _step(records, 2, first, _rename("tester", "qa"))
    _step(records, 3, renamed, _rename("qa", "checker"))
    names = merge(records).names
    assert names is not None
    assert names.current("actors", "tester", [first]) == "checker"
    assert names.current("actors", "qa", [renamed]) == "checker"
    assert names.current("actors", "reviewer", [first]) == "reviewer"


def test_a_name_whose_actor_was_removed_since_is_called_nothing_now() -> None:
    records = _base()
    first = records[0].id
    _step(records, 2, first, [(("actors", "tester"), UNSET)])
    names = merge(records).names
    assert names is not None
    assert names.current("actors", "tester", [first]) is None


def test_a_version_whose_heads_arent_in_the_stream_names_nothing() -> None:
    names = merge(_base()).names
    assert names is not None
    assert names.current("actors", "tester", [_id("elsewhere")]) is None
    assert names.current("actors", "tester", []) is None


def test_a_name_at_an_earlier_version_is_not_the_new_actor_of_that_name() -> None:
    records = _base()
    first = records[0].id
    renamed = _step(records, 2, first, _rename("tester", "qa"))
    _step(records, 3, renamed, [(("actors", "tester"), {"runner": "scripted", "expect": []})])
    names = merge(records).names
    assert names is not None
    assert names.current("actors", "tester", [first]) == "qa"


# Found by an independent review of the merge slice (PR #505)


def test_a_rename_conflict_shows_the_renamed_actor_not_a_new_one_of_its_old_name() -> None:
    """Two lines rename tester; one then makes a new tester. The renames conflict, so the renamed
    actor falls back to tester, and it's that actor config shows while the conflict stands: the
    new one waits. One config mv of tester then resolves it, renaming the actor the renames were
    about."""
    from troupe.core.config.merge import Change

    records = _base()
    base = records[0].id
    left = _step(records, 2, base, _rename("tester", "qa"))
    _step(records, 3, left, [(("actors", "tester"), {**TESTER, "character": "new"})])
    right = _step(records, 4, base, _rename("tester", "qa2"))
    _step(records, 5, right, [(("actors", "qa2", "character"), "edited-on-B")])
    merged = _in_every_order(records)
    assert [c.paths for c in merged.conflicts] == [(("actors", "tester"),)]
    assert merged.config["actors"]["tester"]["character"] == "edited-on-B"
    resolution = change(merged.config, _rename("tester", "qa"))
    resolved = merge(records, extra=Change("proposed", "", {}, "", tuple(resolution), ()))
    assert resolved.conflicts == ()
    assert resolved.config["actors"]["qa"]["character"] == "edited-on-B"
    assert resolved.config["actors"]["tester"]["character"] == "new"


def test_a_rename_and_a_removal_then_a_new_actor_of_the_old_name_conflict() -> None:
    """One line renames tester; the other removes it and makes a new tester. That's a rename
    against a removal, whatever the other line did after: a conflict, never the new actor's values
    landing quietly on the renamed one."""
    records = _base()
    base = records[0].id
    _step(records, 2, base, _rename("tester", "qa"))
    removed = _step(records, 3, base, [(("actors", "tester"), UNSET)])
    _step(records, 4, removed, [(("actors", "tester"), {**TESTER, "character": "fresh"})])
    merged = _in_every_order(records)
    assert [c.paths for c in merged.conflicts] == [(("actors", "tester"),)]
    assert "qa" not in merged.config["actors"]


# Properties for the review's two histories: the conflicts a rename makes, whatever each line does
# after it. The properties above check order and equivalence, so a wrong but deterministic
# conflict got past them.


@st.composite
def _after(
    draw: st.DrawFn, records: list[Record], tip: str, start: int, keep: str | None = None
) -> str:
    """A few more commands on a line, any kind but renames, after ``tip``; none removes the actor
    ``keep`` (removing it on both lines is agreement, not a conflict)."""
    for n in range(start, start + draw(st.integers(0, 3))):
        state = merge(_ancestry(records, tip)).config
        operations = _operation(draw, state, renames=False)
        if operations is None or operations == [(("actors", keep), UNSET)]:
            continue
        entries = change(state, operations)
        if entries:
            tip = _step(records, n, tip, operations)
    return tip


@settings(max_examples=200)
@given(st.data())
def test_a_rename_against_a_removal_conflicts_whatever_each_line_does_after(
    data: st.DataObject,
) -> None:
    records = _base()
    base = records[0].id
    renamed = _step(records, 2, base, _rename("tester", "qa"))
    data.draw(_after(records, renamed, 10, keep="qa"))
    removed = _step(records, 3, base, [(("actors", "tester"), UNSET)])
    data.draw(_after(records, removed, 20))
    merged = merge(records)
    assert any(("actors", "tester") in c.paths for c in merged.conflicts), merged.conflicts


@settings(max_examples=200)
@given(st.data())
def test_two_renames_conflict_and_one_config_mv_of_the_old_name_resolves_them(
    data: st.DataObject,
) -> None:
    from troupe.core.config.merge import Change

    records = _base()
    base = records[0].id
    left = _step(records, 2, base, _rename("tester", "qa"))
    data.draw(_after(records, left, 10, keep="qa"))
    right = _step(records, 3, base, [(("actors", "checker"), Rename(("actors", "tester")))])
    data.draw(_after(records, right, 20))
    merged = merge(records)
    assert any(("actors", "tester") in c.paths for c in merged.conflicts), merged.conflicts
    if [c for c in merged.conflicts if ("actors", "tester") not in c.paths]:
        return  # the lines' later commands conflict too: one rename can't resolve those
    target = next(n for n in ("x1", "x2", "x3") if n not in merged.config.get("actors", {}))
    resolution = change(merged.config, _rename("tester", target))
    assert resolution, merged.config
    resolved = merge(records, extra=Change("proposed", "", {}, "", tuple(resolution), ()))
    assert resolved.conflicts == ()
    assert resolved.config["actors"][target] is not None


def test_config_mv_resolving_a_rename_against_a_rename_and_removal_keeps_the_actor() -> None:
    """One line renames tester to qa; the other renames it to checker and removes it. Resolving
    the conflict with config mv keeps the actor: the removal it chose against stays left out."""
    from troupe.core.config.merge import Change

    records = _base()
    base = records[0].id
    _step(records, 2, base, _rename("tester", "qa"))
    renamed = _step(records, 3, base, _rename("tester", "checker"))
    _step(records, 4, renamed, [(("actors", "checker"), UNSET)])
    merged = _in_every_order(records)
    assert [c.paths for c in merged.conflicts] == [(("actors", "tester"),)]
    resolution = change(merged.config, _rename("tester", "x1"))
    resolved = merge(records, extra=Change("proposed", "", {}, "", tuple(resolution), ()))
    assert resolved.conflicts == ()
    assert resolved.config["actors"]["x1"] == TESTER
