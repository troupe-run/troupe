# Design

## Context

See proposal.md for why. How the merge works today (`troupe.core.config.merge`, config-model design D3):

- For each **point** (a path an entry names), the **covering writes** are the entries at it or at a group above it,
  and its **latest writes** are those that no later covering write follows. `_contest` takes the covering writes and
  returns what to leave out of replay, plus the latest writes left in conflict.
- A latest write's **line** is the covering writes behind it that the other latest writes don't descend from. A line
  whose writes are all at the point and end where they began drops out. If the lines left disagree, that's a
  conflict, and every latest write's line is left out.
- **Replay** applies every entry that isn't left out, in the store's order (any order that keeps parents before
  children). The module docstring says entries that are left in and concurrent never overlap, so the order can't
  matter.

That claim holds only while something at the frontier stays in, because those writes come after everything beneath
them in every order. When nothing stays in (a conflict, or every line dropping out), replay falls back to the
covering writes beneath the lines. Those can be concurrent writes from an older fork that a settle joined, and
`_contest` never looked at them.

#190's saved history, with `reviewer.expect` as the point (`[]` in the base):

| Version | Parents | Write |
|---|---|---|
| 1 | | base: `[]` |
| 6 | 3 (after 1) | `[]` → `["a.txt"]` |
| 8 | 1 | `[]` → `["a.txt"]` |
| 10 | 8 | `["a.txt"]` → `[]` |
| 12 | 6, 10 | settle |
| 14 | 12 | `["a.txt"]` → `[]` |
| 15 | 12 | `["a.txt"]` → `["b.txt"]` |

The latest writes are 14 and 15, and they conflict, so both are left out. Writes 6, 8 and 10 stay in replay. 6 and
10 are concurrent, so the last of them in the store's order decides: `["a.txt"]` if 6 comes last, `[]` if 10 does. At
the settle, the same rule had worked the point out as `["a.txt"]`: 8 and 10 are a line that changes the value and
changes it back, so they drop out, and 6 decides. 14 and 15 both start from that value.

Checked in a scratch copy, without changing the project: the saved example replays from #188's `.hypothesis/`, and
both of the spec delta's new scenarios, built as records, give two different results across their orders on main (6
and 18 orders).

## Goals / Non-Goals

**Goals:**
- The merge is a function of the history's graph alone: every order that keeps parents before children gives the
  same config, conflicts and heads.
- Where something at the frontier stays in, the result is the same as today. The change only affects points where
  nothing stays in.
- Which conflicts are reported, and what each one names, stays the same.

**Non-Goals:**
- Changing which conflicts are reported (D2).
- Reading a settling event's state. It stays a join only (config-model D3).

## Decisions

### D1. When nothing at the frontier stays in, contest what's left, and repeat

`_contest` keeps its first round as it is, and then loops:

1. If the round left a latest write's line in (they agreed, or some lines dropped out and the rest agreed), stop:
   those writes come after everything else left in, in every order, so they decide.
2. Otherwise (the lines conflicted, or every line dropped out), run the same rule again on the covering writes that
   aren't left out yet. Add what that round leaves out to the set. Use the same ancestry, and recompute the latest
   writes among what's left, since the writes already left out follow everything beneath them.
3. Stop when one covering write's event is left as the latest, or none are left.

Every round that goes on leaves out at least its latest writes, so the loop ends. Each round depends only on the
graph and the writes, never on the store's order, so the result doesn't either. For #190's history, the second round
finds 6 and 10 as the latest, drops the line 8 → 10 as a change and change back, and keeps 6: config shows
`["a.txt"]`, the value the settle left.

The loop stays inside `_contest`, so `merge`, `apply_in_order`, `_grouped` and `_invalid` don't change. The module
docstring's "Replay" paragraph is changed to say what replay now relies on, and `contributing/config.md`, "The merge",
gets the same sentence.

Alternatives:
- **Replay concurrent writes in a fixed order** (by event id, say). It's deterministic, but the value then depends on
  hashes, not on the history: in #190's history it could pick 10's `[]`, from a line the settle treated as no change.
  Rejected.
- **Use the settling event's state as a base.** The settle's state is a snapshot for the library, and config-model D3
  reads it as a join only, so every clone that settles the same heads agrees. Not every fork beneath a conflict is
  settled (two lines can merge without a settle until the next write), and a criss-cross history has no single base.
  Rejected, as in config-model D3.
- **Run the whole merge again on the history beneath the conflict** (its common ancestry). It gives the same answer
  as D1 for the point, but it works on whole sub-histories rather than one point's writes, and it would need its own
  rule for what "beneath" is when there are three or more latest writes. D1 gets that from the writes it hasn't left
  out yet. Rejected as more machinery for the same result.

### D2. Only the first round's conflict is reported

A later round only decides the value config shows. It never adds a conflict. When the first round conflicts, that's
already reported, and each later write descends from the older fork, so each line has already dealt with it. When
every first-round line drops out, each of them changed the value after the older fork and changed it back, so each
line resolved that fork's conflict, if it had one. (A change recorded while config has a conflict has to set every
conflicting value.) Today these rounds don't run at all, and nothing beneath is reported, so this keeps reporting the
same.

### D3. Tests

- **#190's history as a plain test** in `test_config_merge_properties.py`, built with the file's `_changed` and
  `_settled` helpers and the saved example's versions and entries, so its ids match the saved example. It goes
  through every order that keeps parents before children (12 of them) and checks that each gives `reviewer.expect ==
  ["a.txt"]`, one conflict at `actors.reviewer.expect` naming versions 14 and 15, and heads 14 and 15. It's a plain
  test, not `@example`, because the property draws its history and orders from `st.data()`, which an `@example`
  can't supply. A small helper that lists every such order is shared with the scenario checks.
- **The two new scenarios** go in `test_config_merge.py`, through a real store and git branches: merge two branches,
  let a `config set` settle them, branch again, and change `tester`'s character on both sides. Each checks the value
  and conflicts from `config_of`, and the "whatever order" part with a records-level test next to #190's, through every
  order.
- **The order property draws more examples:** from 150 to 500, since 150 missed this history on CI. The test takes
  about 1.5 s for both properties today, so it's measured before and after, and the count is kept lower if the
  increase is more than a few seconds.
- **What must not change is pinned before any code.** The existing merge tests (`test_config_merge.py`,
  `test_config_merge_files.py`, `test_cli_config_merges.py`, both properties) pass on main and must pass unchanged.
  The conflict oracle property (`test_a_conflict_is_reported_exactly_where_two_branches_end_a_value_differently`)
  covers D2 for forks from one base.

### D4. A line whose first writes disagree about where it began is a change

Found by task 3.2's seed run (seed 31), and on main too: a line can hold concurrent writes, from a fork that a settle
joined inside it. The line's net change then has no single first `before`, and taking the first in the store's order
makes the result depend on it. In the found history, heads 10 (`A` → `B`) and 14 disagree. 14's line is 11 (`A` →
`B`) and 12 (absent → `A`), concurrent, joined by a settle that conflicted, then 14, which resolved it to `A`. With 11
first, the line changes the value and back, so it drops out and `B` wins. With 12 first, it's a conflict. Main gives
`B` in 5 of the 14 orders and a conflict in the other 9.

A line's **first writes** are its writes that no other write in the line comes before. The line drops out only when
it's all at the point and **every** first write's `before` is the value it ends at. Otherwise it counts as a change.
Owner, 2026-10-29, choosing this over the alternative: it's conservative. It can't quietly override a value someone
chose when they resolved a conflict, and here it makes `B` against `A` a conflict that a person decides. For a line
with one first write (every chain, so every branch off one base), the rule is the same as today's.

Alternative: measure the net change from the value where the lines split, worked out from their shared history by
the same rule. Here that's `A` to `A`, so the line drops out and `B` wins with no conflict. It reads "since the lines
split" literally, but it needs a rule for "shared" when there are three or more lines, and it overrides the `A`
resolution without asking. Not chosen.

## Risks / Trade-offs

- **[One unexplained failure in the prototype run]** A scratch prototype of D1, patched over `_contest`, passed the
  saved example, the merge and config tests, and 134 of 135 seeded runs of both properties. The one failure, in the
  first 25-seed batch and taking 16 s, wasn't captured, and the same 25 seeds passed twice afterwards. It may have
  been the shrinker on a real failure, or something in the run. → Mitigation: the implementation runs both properties
  over at least 100 seeds, output kept, and any failure becomes an explicit test before the change is done. That run
  found seed 31, a second order bug that main has too (D4), which is probably what the prototype hit.
- **[A later round costs time]** Each extra round goes over the point's covering writes again. Config histories are
  small, and the rounds run only at points where nothing at the frontier stays in. → The merge and property tests are
  timed before and after.
- **[A conflict beneath could matter in one shape]** With three or more latest writes, a write can be shared by two
  lines but not the third. If every first-round line drops out there, two lines can each have returned to a
  different older value, and D2 reports no conflict, as today. → Open question below. The fix doesn't make this
  worse: today's result in that shape depends on the order as well.

## Migration Plan

None. The merge is worked out on every read and nothing is stored, so every clone gets the fixed result once it
updates. Histories that already gave the same answer in every order give the same answer as before.

## Open Questions

- **Should a conflict beneath the frontier ever be reported?** (D2 and the last risk.) It doesn't change this fix,
  its spec or its tasks, since today's reporting is kept. If the owner wants it looked at, it's a follow-up issue,
  with a generated history that shows the three-line shape first.
