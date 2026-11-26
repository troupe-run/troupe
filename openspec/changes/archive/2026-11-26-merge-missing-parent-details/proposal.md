# Proposal

## Why

troupe#506: when config's merge finds an event whose parent isn't here, it raises `events.missing-parent` with only
`missingParent` and `onlyIn` in its details. The protocol (`error.schema.json`) also requires `line` and `event`, which
the text store's own refusal of the same thing gives. So the error troupe sends a client for a broken config stream
doesn't match the protocol, and no test reaches it to notice.

The check can't simply go in favour of the store's. The store's `history()` deliberately refuses nothing (an aggregate
that merges its own forks reads its stream that way and checks parents itself: config-model design D5), and config is
read through `history()`. So a config segment whose parent's file was removed reaches merge's check, and only that one.

## What Changes

- Config merge's `events.missing-parent` details carry `line` (the line of the event's segment) and `event` (its ID),
  as the text store's do, alongside `missingParent` and `onlyIn`.
- A test removes a config event's file by hand in a real git theatre, reads config, and checks the error, under the
  protocol guard, which validates the details against the schema. It fails on main.
- The test copy of the old merge (`tests/merge_oracle.py`) gets the same details, so it can't build an invalid error.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `event-store`: "A missing parent is refused" gains a scenario saying config's reads refuse it the same way, with the
  event and its line named.

## Impact

- `packages/troupe/src/troupe/core/config/merge.py` (`_check_parents`), `packages/troupe/tests/merge_oracle.py`.
- A new integration test in `packages/troupe/tests/integration/test_config_merge.py`.
- No protocol change: the schema already requires both keys.
