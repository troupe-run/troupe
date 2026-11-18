# Proposal

## Why

Two TextStores on one theatre (two processes, or two instances in one process) each load the local order log
(`.troupe/local/order/<branch>.jsonl`) and tracking log once and cache them, reloading only on a branch change. When
one records an event, the other still sees it as unordered, takes the write lock and appends it again under the
same notification id. The next store to load the file refuses it ("expected notification id 3"), so every command
on that clone fails (troupe-run/troupe#450). Any reader beside a run does this: `troupe logs --follow`, or a port
subscriber. It breaks the event-store requirement that notification IDs are dense and never renumbered.

## What Changes

- Under the write lock, before ordering or appending, the store brings its cached order and tracking logs up to date
  with the files: it reads lines appended since it last looked, and reloads in full when the file was rebuilt under
  a new epoch or replaced. So concurrent writers on one theatre never append a notification id twice, and a
  follower's position recorded by another store is seen before a new one is checked.
- Reading outside the write lock never trims a torn last line, because another writer may be part-way through an
  append; only a store holding the lock trims one (today a first load outside the lock could).
- An order log already damaged by this bug: handling depends on the owner's answer (see design D4). Recommended:
  drop exact duplicate lines on load and rewrite the file under the lock, with a notice; anything else is refused as
  today.

## Capabilities

### New Capabilities

### Modified Capabilities
- `event-store`: "Notification IDs are local, dense and never renumbered" gains a scenario for two stores on one
  theatre; "Followers' positions are local" gains one for a position recorded by another store.

## Impact

- `packages/troupe-store-text/src/troupe_store_text/local.py` (OrderLog, TrackingLog: catch-up reads) and
  `store.py` (`_local` catches up under the write lock).
- Tests in `packages/troupe-store-text/tests/` from the issue's repro, across instances and across processes.
- A fix, so it releases (0.2.0 milestone). No protocol, schema or CLI change.
