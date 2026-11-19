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
- An order log already damaged by this bug is mended, by the owner's decision (design D5). An exact repeat of a line
  is dropped and the file rewritten under the same epoch, with a new `events.order-repaired` notice, so followers
  keep their place. A conflict (one id naming two events, or an id out of sequence) rebuilds the order under a new
  epoch with `events.order-rebuilt`, whose details now say which line and why, and followers start again.
- The subscription wakes listeners when the order's epoch changes, not only when its length does.

## Capabilities

### New Capabilities

### Modified Capabilities
- `event-store`: "Notification IDs are local, dense and never renumbered" gains a scenario for two stores on one
  theatre; "Followers' positions are local" gains one for a position recorded by another store; "The local order
  rebuilds itself when events disappear" also covers an order that names two events by one id; a new requirement
  covers dropping repeated lines.

## Impact

- `packages/troupe-store-text/src/troupe_store_text/local.py` (OrderLog, TrackingLog: catch-up reads) and
  `store.py` (`_local` catches up under the write lock).
- Tests in `packages/troupe-store-text/tests/` from the issue's repro, across instances and across processes.
- `protocol/schemas/notice.schema.json` (a new notice, and `events.order-rebuilt`'s details), the generated
  models, `troupe.core.notices`, and contributing/event-store.md.
- A fix, so it releases (0.2.0 milestone). No CLI change.
