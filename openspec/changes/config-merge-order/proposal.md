# Proposal

## Why

The config merge can work out a different config depending on the order a clone received the events in (#190). That
breaks the config spec's "Every clone agrees" scenario: two clones with the same history can disagree about an actor,
so the same `troupe perform` does different things on each. Hypothesis found it locally on main as of 4c00c48. CI
hasn't drawn the history yet, so it's green. The saved example now fails every local commit in the #188 worktree, so
it blocks #188 and the release pull request #89.

The cause, from the saved example: a fork (one line sets `reviewer.expect` to `["a.txt"]`, the other sets it and sets
it back) is settled, and the settle works out `["a.txt"]`. Two changes after the settle then set it differently, so
they conflict, and both are left out of replay. The merge only looks at a point's latest writes, so nothing settles the
older fork beneath them again. Replay then takes whichever of the older fork's concurrent writes comes last in the
store's order: `["a.txt"]` in one order and `[]` in another. The merge module says entries that are left in and
concurrent never overlap, but here they do.

## What Changes

- **When no line's change is left at a point, the history beneath decides, by the same rule.** If a point's latest
  lines conflict, or every one of them drops out because it ends where it began, the merge works out the point again
  from the writes it hasn't left out, and keeps going down until one write is left or a line's change stays in. So a
  conflict or a dropped line never leaves the store's order to decide the value. In #190's history, config shows
  `["a.txt"]` with the conflict between changes 14 and 15, which is the value the settle left and both changes started
  from.
- **Conflicts are reported as they are today.** Only the latest lines' conflict is reported. Working out the history
  beneath only decides which value config shows while the point is in conflict, or once its lines drop out (design D2).
- **#190's history becomes an explicit test,** built from its records, which checks every order its events can arrive
  in. So it runs on every machine, not only one whose `.hypothesis/` holds it.
- **The merge's docs say what replay leaves to the history beneath:** the `troupe.core.config.merge` module docstring
  and `contributing/config.md`, "The merge".

Out of scope:
- what config shows for a conflicted value in `config get` beyond this rule (no change to its output shape);
- reporting a conflict in the history beneath the latest lines (design D2 explains why it stays unreported, and names
  the one case where that could matter, as an open question for the owner);
- changing the history generator, other than how many examples the order property draws (design D3).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `config`: "A merge combines each line's net change" says that where no line's change is left at a value, the
  history before those lines works it out by the same rule. It gains two scenarios: a conflict after a settle shows the
  value the settle left, and lines after a settle that each change a value and change it back leave the value the
  settle left, both in every order the events arrive in.

## Impact

- `packages/troupe/src/troupe/core/config/merge.py`: `_contest` works the point out again from what it hasn't left out,
  and the module docstring's "Replay" paragraph changes.
- `packages/troupe/tests/test_config_merge_properties.py`: #190's history as a plain test over every order, and the
  order property's example count.
- `packages/troupe/tests/test_config_merge.py`: the two new scenarios, through a real store.
- `contributing/config.md`: "The merge".
- Issues: closes #190, which unblocks #188 and #89.
