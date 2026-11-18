# Proposal

## Why

When a branch's local order is rebuilt (an ordered event is gone, or since troupe-run/troupe#450 a conflicting
order), the text store numbers the new order from 1 again under a new epoch. A follower that read ids under the old
epoch can then skip events in the new one (troupe-run/troupe#454):

- **A position recorded across the rebuild.** A follower pulls ids 1..2 under epoch E1, another process rebuilds the
  order under E2, and the follower records `Tracking("f", 2)`. The library's `Tracking` carries no epoch, so it's
  stored as E2/2, and E2's ids 1..2 are never delivered to it.
- **A live subscription across the rebuild.** The library's subscription keeps its own position in memory. Having
  delivered 1..3, after a rebuild it goes on from 4, so E2's ids 1..3 are never delivered, with no position recorded.

The house (troupe-run/troupe#63) will keep projections live through subscription-driven eventsourcing runners, which
pull notifications on one thread and record positions on another, sometimes in another store. So the store can't
tell which epoch a position was read under. This needs settling before troupe's first follower records positions.

## What Changes

- By the owner's decision (2026-11-18, option 4 of #454), a notification id is **never reused on a branch**. A
  rebuilt order numbers its events after the highest id ever issued there, so E1 = 1:a 2:b 3:c is rebuilt as
  E2 = 4:a 5:b 6:c. Any position or subscription from an older epoch is below every new id, so a follower is given the
  whole new order again (at least once), whatever runner or thread it uses and wherever it keeps its position.
- Ids are dense from 1 only until the first rebuild; each order is dense from where it starts. The order file's
  epoch line says where the order starts (`{"epoch": ..., "after": n}`).
- The highest id issued is kept in its own local file beside the order (`.troupe/local/issued/<branch-key>.json`),
  so deleting the order file by hand, which the store's fix-it message tells people to do, doesn't reset numbering
  to 1.
- **BREAKING (local state only):** an order file whose epoch line has no `"after"` (written before this change) is
  refused as malformed, with the existing fix: delete it and troupe rebuilds it. Pre-1.0, no compatibility form.

## Capabilities

### New Capabilities

### Modified Capabilities

- `event-store`: notification ids are dense until a rebuild and never reused on a branch; a rebuild numbers after
  the highest id issued, which survives deleting the order file; a follower across a rebuild, by its recorded
  position or a live subscription, is given every event of the new order.

## Impact

- `packages/troupe-store-text`: `local.py` (`OrderLog`'s epoch line, numbering from `after`, the issued mark),
  `store.py` (notifications and `max_notification_id` from where the order starts; rebuilds pass the mark).
- Tests in `packages/troupe-store-text/tests` (`test_shared_theatre.py`, the ordering state machine), and the
  `write_order` helper's epoch line.
- `contributing/event-store.md` (Ordering, the local files) and the event-store spec.
- No protocol or notice schema changes: `events.order-rebuilt` keeps its details.
