# Proposal

## Why

troupe#532: config's merge works out a different config from the same events in a different order when the history
holds renames. Hypothesis found the history: reviewer is removed on one line and renamed to qa on another, a settle
joins them, and later one line makes a new tester while the other renames reviewer to tester. Depending on which of
the early removal and rename arrived last, reviewer is lost or its values show up as the new tester. Config must come
out the same whatever order a merge reads the events in. This is one of config's core properties.

The cause is in the name contest (`core/config/entities.py`). The two testers clash, so the rename of reviewer to
tester is left out and reviewer falls back to an earlier name. The writes it falls back onto (the removal and the
rename to qa) are concurrent. The contest left them alone while the later rename covered them, and they aren't
contested again once it's left out, so whichever arrived last wins.

## What Changes

- When a clash leaves a key's renames out, that key's remaining name writes are contested again by the name contest's
  usual rule before its name is worked out. This is what the value contest already does when a write covering others
  is left out (#503). In the found history, the removal and the rename to qa conflict, so reviewer keeps its own name.
  In every order, config has qa, reviewer and the new tester, with the clash on tester.
- A test pins the found history and checks that every order it can arrive in gives that config and conflict. It fails
  on main.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `config-renames`: "Renames that can't both hold are a conflict" gains a scenario saying that a rename left out by a
  clash falls back to the name its history works out, the same in every order.

## Impact

- `packages/troupe/src/troupe/core/config/entities.py` (the clash settling).
- `packages/troupe/tests/unit/test_config_merge_renames.py` (the pinned history).
- No protocol or schema change.
