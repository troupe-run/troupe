# Design

## Context

See proposal.md for the gap. The parts of the text store it touches (`packages/troupe-store-text`):

- `local.py`'s `OrderLog` reads `.troupe/local/order/<branch-key>.jsonl`: an `{"epoch": ...}` line, then
  `{"n": 1, "event": ...}`, `{"n": 2, ...}`. `ids[n - 1]` is the event with id n. `rebuild` rewrites the file
  under a new epoch from 1. A line out of sequence is a conflict, which rebuilds (troupe-run/troupe#450, D5).
- `TrackingLog` keeps positions per `(epoch, application name)`; `max_tracking_id` reads the current epoch only, so
  after a rebuild a follower that asks for its position gets none and starts from 1 (order-log-shared D6).
- The library's subscription (`ListenNotifySubscription`) pulls on its own thread from its last id, into a queue of
  up to ten batches; runners record positions on another thread, and `ProjectionRunner`'s tracking recorder can be
  a different store. Nothing in a `Notification` or `Tracking` carries an epoch.

Two probes fail today: a position read under E1 and recorded under E2 skips E2's first ids, and a live subscription
across a rebuild goes on from its last id (proposal.md).

## Goals / Non-Goals

**Goals:**
- No follower skips an event of a rebuilt order, whichever eventsourcing runner it uses, on whatever threads, and
  wherever its position is kept.
- Deleting the order file by hand, as the fix-it messages say to, never makes an id name a different event.

**Non-Goals:**
- Exactly-once delivery across a rebuild. Delivery stays at least once: a follower is given the rebuilt order's
  events again under new ids, as order-log-shared D6 intends.
- Translating positions across a rebuild (option 3 of #454).
- Keeping the highest id issued when the whole `.troupe/local/` directory is deleted (D4).

## Decisions

### D1. A notification id is never reused on a branch (owner decision)
Owner decision (2026-11-18, troupe-run/troupe#454, option 4): a rebuild numbers the new order after the highest id
ever issued on the branch. E1 = 1:a 2:b 3:c is rebuilt as E2 = 4:a 5:b 6:c. Any position from an older epoch, recorded
before or after the rebuild, and any subscription's in-memory position, is below every id of the new order, so the
next read from it gives the whole new order. Nothing has to tell which epoch a position was read under.

Alternatives, all set out for the owner with input → outcome examples on #454:
- *1. The store remembers the epoch it served and drops a position recorded after it changed.* Under the
  subscription-driven runners the house will use (troupe-run/troupe#63), the pull thread is already on E2 while the
  processing thread records E1's position, so a stale position is accepted. It can't work when the tracking recorder
  is another store, and it doesn't fix a live subscription.
- *2. troupe's followers carry the epoch in their own tracking.* Works only for followers troupe writes itself, on a
  runner and subscription troupe owns instead of the library's.
- *3. Translate positions across a rebuild.* Ambiguous for a conflict rebuild, can't tell a position read under E1
  if it's recorded after the rebuild, and doesn't fix a live subscription.

### D2. The epoch line says where the order starts
The first line becomes `{"epoch": ..., "after": n}`, n ≥ 0: the order's ids run from n + 1 with no gaps. A new
branch's first order has `"after": 0`. `ids[i]` is the event with id `after + i + 1`; a line is in sequence when its
id is `after + len(ids) + 1`, and a repeat when it names the event already at that id (D5 of order-log-shared,
offset). `_still_there` compares the whole first line, so a rebuild that happened to reuse an epoch string would
still be seen.

The store reads notifications from `max(low, after + 1)`, and `max_notification_id` is `after + len(ids)`, or none
when the order has no events (no id names an event, as in a fresh store).

An epoch line without `"after"` (written before this change) is malformed (`events.malformed-record`, with the
fix to delete the file): pre-1.0, no compatibility form (no-compat-leniency).

### D3. The highest id issued is kept apart from the order: `issued/<branch-key>.json`
`.troupe/local/issued/<branch-key>.json` holds `{"issued": n}`: no id above n has been issued on the branch. It is
written whole, by atomic replace (`troupe.core.files.replace_file`), so it's never torn.

- **Reserve before issuing.** Under the write lock, before order lines that would pass n are appended, the store
  raises n to the new last id plus `defaults.ORDER_ID_RESERVE` (1024). One extra atomic write per 1024 ids, rather
  than two more fsyncs on every insert. A crash between the two writes leaves the mark above the order, never below.
- **Every new order starts after the mark.** When an order is started or rebuilt (a gone event, a conflict, or a
  missing file), `after` is the largest of the mark, the old order's last id (when it's still readable), and the
  last id this store has seen in memory. The gap this leaves (up to the reserve) appears only at a rebuild.
- **A conflicting order still counts its ids.** Reading stops at a conflicting line, but the ids that line and the
  lines after it name may have been issued, so the highest of them counts too. Found by the test that deletes the
  mark alone: the order a@1 b@2 b@3 stops at b@3, and without this the rebuild reused id 3.
- Why not keep it in the order's epoch line alone: deleting the file, as its own fix-it message says, would take it
  with it. Why not in the tracking file: that file is followers' state, and its fix-it is also "delete it".

### D4. What deleting local files does, and what the messages say
- **The order file** (malformed): the fix stays "delete it and troupe rebuilds it", now true: the rebuilt order is
  numbered after the mark in `issued/`, and followers start again from the beginning.
- **The issued file missing:** the store falls back on the order's last id, so deleting it alone loses nothing.
- **The issued file malformed** (`events.malformed-record`, naming the file): it can't be rebuilt from the events,
  so the fix says what it is and how to mend it: write `{"issued": n}` with n at least the last id in the order
  file. Deleting it as well as the order file makes ids start at 1 again, and the message says that any projection
  that keeps its position outside troupe must then be rebuilt.
- **The whole `.troupe/local/` directory:** the mark goes with it and ids start at 1. troupe's own followers' positions
  (`tracking/`) go too, so they start again; a projection keeping its position elsewhere must be rebuilt by hand.
  contributing/event-store.md says so. Keeping the mark outside the theatre (a user-level directory) was weighed and
  left out: it would tie a clone's local state to one machine user, against addressing theatres by id.

### D5. Positions stay per epoch
`TrackingLog` is unchanged: a position counts only under the epoch it was recorded under, so after a rebuild
`max_tracking_id` is none and the follower starts from the beginning, as the spec's rebuild scenarios say. A stale
position recorded after a rebuild is stored under the new epoch, but it's below every id of the new order (D1), so
it skips nothing. The check that a new position is greater than the last is unchanged.

## Risks / Trade-offs

- [Ids have a gap after a rebuild] → The library tolerates gaps (PostgreSQL's ids have them). The spec now says ids
  are dense until a rebuild, and dense within each order.
- [A rebuild jumps ids by up to the reserve] → Notification ids are internal; nothing shows them to people.
- [Old local order files are refused] → One clear error with the existing fix (delete it); pre-1.0.
- [Deleting all of `.troupe/local/` resets ids] → Documented (D4); troupe's own followers start again with it.

## Migration Plan

None beyond D2: an order file from before this change is refused with the fix to delete it, and the store rebuilds it.
