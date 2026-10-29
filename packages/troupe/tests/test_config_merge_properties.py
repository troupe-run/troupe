"""The config merge, over generated histories (spec: config, "Every clone agrees"; config-model
design D3).

The merge is a pure function of the config stream's history, so these build histories in memory:
branches, changes and changes back, settles, and criss-cross merges where two lines settle each
other. Two properties:

- **Order doesn't matter.** Every order the events can arrive in (any order that keeps parents
  before children) works out the same config and the same conflicts, so every clone agrees.
- **Conflicts are exactly the differing net changes.** For a base and branches off it, an oracle
  replays each branch on its own: a path is in conflict exactly when two branches end it
  differently from the base and from each other, and otherwise the merged value is the one
  branch's change, or the base's.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from troupe.core.config import aggregate
from troupe.core.config.changes import Tree, apply, change, get
from troupe.core.config.merge import Merged, merge

TESTER: dict[str, Any] = {
    "runner": "scripted",
    "options": {"script": {"steps": [{"exit": 0}]}},
    "expect": [],
}
ACTORS = ("tester", "reviewer")
FIELDS = ("character", "expect")
VALUES: dict[str, list[Any]] = {"character": ["A", "B", "C"], "expect": [[], ["a.txt"], ["b.txt"]]}
PATHS = [("actors", actor, name) for actor in ACTORS for name in FIELDS]


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


def _base() -> tuple[list[Record], Tree]:
    entries = change({}, [(("actors", actor), dict(TESTER)) for actor in ACTORS])
    return [_changed(1, [], entries)], apply({}, entries)


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


@st.composite
def histories(draw: st.DrawFn) -> list[Record]:
    """Branches that change, change back, fork and settle each other, in creation order."""
    records, _ = _base()
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
        path = draw(st.sampled_from(PATHS))
        value = draw(st.sampled_from(VALUES[path[-1]]))
        entries = change(state, [(path, value)])
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


def _summary(merged: Merged) -> tuple[object, ...]:
    return (
        json.dumps(merged.config, sort_keys=True),
        sorted((c.paths, sorted(x.id for x in c.changes), c.rule) for c in merged.conflicts),
        merged.heads,
    )


@settings(max_examples=500)
@given(st.data())
def test_every_order_the_events_can_arrive_in_works_out_the_same_config(
    data: st.DataObject,
) -> None:
    records = data.draw(histories())
    first = _summary(merge(records))
    for _ in range(3):
        again = _orders(data, records)
        assert _summary(merge(again)) == first


@st.composite
def branches(draw: st.DrawFn) -> tuple[list[Record], Tree, list[Tree]]:
    """A base, then two or three branches off it, each a chain of changes (some changed back)."""
    records, base = _base()
    n = 2
    finals: list[Tree] = []
    for _ in range(draw(st.integers(2, 3))):
        tip, state = records[0].id, base
        for _ in range(draw(st.integers(1, 4))):
            path = draw(st.sampled_from(PATHS))
            if draw(st.booleans()):
                value: object = get(base, path)  # back to the base's value
            else:
                value = draw(st.sampled_from(VALUES[path[-1]]))
            if value is None:
                continue
            entries = change(state, [(path, value)])
            if not entries:
                continue
            record = _changed(n, [tip], entries)
            n += 1
            records.append(record)
            tip, state = record.id, apply(state, entries)
        finals.append(state)
    return records, base, finals


@settings(max_examples=200)
@given(branches())
def test_a_conflict_is_reported_exactly_where_two_branches_end_a_value_differently(
    drawn: tuple[list[Record], Tree, list[Tree]],
) -> None:
    records, base, finals = drawn
    merged = merge(records)
    conflicted = {path for c in merged.conflicts for path in c.paths}
    for path in PATHS:
        was = get(base, path)
        ended = {json.dumps(get(final, path)) for final in finals if get(final, path) != was}
        if len(ended) > 1:
            assert path in conflicted, path
        else:
            assert path not in conflicted, path
            expected = json.loads(ended.pop()) if ended else was
            assert get(merged.config, path) == expected, path


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


def _step(records: list[Record], n: int, parent: str, path: tuple[str, ...], value: object) -> str:
    """Record version ``n``, a change to ``path`` after ``parent``, worked out from its history."""
    state = merge(_ancestry(records, parent)).config
    record = _changed(n, [parent], change(state, [(path, value)]))
    records.append(record)
    return record.id


def _issue_190() -> list[Record]:
    """#190's history: a fork settled, then two changes after the settle that conflict."""
    expect = ("actors", "reviewer", "expect")
    records, _ = _base()
    left = _step(records, 3, records[0].id, ("actors", "tester", "character"), "A")
    left = _step(records, 6, left, expect, ["a.txt"])
    right = _step(records, 8, records[0].id, expect, ["a.txt"])
    right = _step(records, 10, right, expect, [])  # and back
    settled = _settled(12, [left, right])
    records.append(settled)
    _step(records, 14, settled.id, expect, [])
    _step(records, 15, settled.id, expect, ["b.txt"])
    return records


def test_issue_190s_history_shows_the_settled_value_and_one_conflict_in_every_order() -> None:
    records = _issue_190()
    later = [_id(("change", 14)), _id(("change", 15))]
    orders = _every_order(records)
    assert len(orders) == 12
    for order in orders:
        merged = merge(order)
        assert get(merged.config, ("actors", "reviewer", "expect")) == ["a.txt"]
        assert [(c.paths, sorted(x.id for x in c.changes)) for c in merged.conflicts] == [
            ((("actors", "reviewer", "expect"),), sorted(later))
        ]
        assert merged.heads == tuple(sorted(later))


CHARACTER = ("actors", "tester", "character")


def _settled_fork(records: list[Record]) -> str:
    """Two branches set ``tester``'s character, one to new text and one to other text and back,
    and a settle joins them: the settle leaves the new text."""
    base = _step(records, 2, records[0].id, CHARACTER, "Original.")
    left = _step(records, 3, base, CHARACTER, "New.")
    right = _step(records, 4, base, CHARACTER, "Other.")
    right = _step(records, 5, right, CHARACTER, "Original.")
    settled = _settled(6, [left, right])
    records.append(settled)
    assert get(merge(records).config, CHARACTER) == "New."
    return settled.id


def test_a_conflict_after_a_settle_shows_the_value_the_settle_left_in_every_order() -> None:
    records, _ = _base()
    settled = _settled_fork(records)
    _step(records, 7, settled, CHARACTER, "X.")
    _step(records, 8, settled, CHARACTER, "Y.")
    orders = _every_order(records)
    assert len(orders) == 6
    for order in orders:
        merged = merge(order)
        assert get(merged.config, CHARACTER) == "New."
        assert [c.paths for c in merged.conflicts] == [(CHARACTER,)]


def test_lines_after_a_settle_that_change_a_value_back_leave_the_settled_value_in_every_order() -> (
    None
):
    records, _ = _base()
    settled = _settled_fork(records)
    for n, text in ((7, "X."), (9, "Y.")):
        changed = _step(records, n, settled, CHARACTER, text)
        _step(records, n + 1, changed, CHARACTER, "New.")  # and back
    orders = _every_order(records)
    assert len(orders) == 18
    for order in orders:
        merged = merge(order)
        assert get(merged.config, CHARACTER) == "New."
        assert merged.conflicts == ()


def test_a_line_whose_first_changes_start_from_different_values_conflicts_in_every_order() -> None:
    """Seed 31's history: 14's line is 11 (``A`` to ``B``) and 12 (none to ``A``), concurrent and
    joined by a settle, then 14 back to ``A``. Against 10's ``B``, that's a conflict."""
    records, _ = _base()
    first = _step(records, 4, records[0].id, CHARACTER, "A")
    _step(records, 10, first, CHARACTER, "B")
    one = _step(records, 11, first, CHARACTER, "B")
    other = _step(records, 12, records[0].id, CHARACTER, "A")
    settled = _settled(13, [one, other])
    records.append(settled)
    _step(records, 14, settled.id, CHARACTER, "A")
    orders = _every_order(records)
    assert len(orders) == 14
    summaries = {repr(_summary(merge(order))) for order in orders}
    assert len(summaries) == 1
    merged = merge(records)
    assert [(c.paths, sorted(x.id for x in c.changes)) for c in merged.conflicts] == [
        ((CHARACTER,), sorted([_id(("change", 10)), _id(("change", 14))]))
    ]
