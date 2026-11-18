# Design

## Context

`TextStore` keeps this branch's `OrderLog` and `TrackingLog` (`local.py`) in memory and reloads them only when the
branch key changes (`store._local`). The event segments, by contrast, are read incrementally on every call
(`refresh`), so a store sees another store's events but not the notification ids that store gave them. `_pending`
then lists those events as waiting, `_order_locked` appends them again, and the file gets two lines with the same
`n`. `OrderLog.load` refuses such a file. The same staleness affects `TrackingLog`: `_check_tracking` compares with a
cached position, so a second store can record a position that isn't greater than one already recorded.

Writes are serialised across processes by the directory lock in `local/` (design D10 of the event-store change);
`append_bytes` returns the file's size before the append. `replace_file` (used by `OrderLog.rebuild`) replaces the
file atomically under a new epoch.

## Goals / Non-Goals

**Goals:**
- Every store on a theatre, in any process, agrees on the notification order and appends a notification id only
  once (the event-store spec's "Notification IDs are local, dense and never renumbered").
- A follower's position recorded by one store is seen by the others before they check or record one.
- Keep reads cheap: catching up costs a `stat` and the bytes appended since the last look, not a full re-read.

**Non-Goals:**
- Changing the files' format, the lock, or how the order is computed (`_replay_order`).
- Sharing one in-memory store across processes.

## Decisions

### D1. The local logs catch up with their files on every use, not only on a branch change
`OrderLog` and `TrackingLog` remember how many bytes they've consumed (`offset`) and the epoch they read.
`catch_up()` reads the first line's epoch and the file's size: if the file is gone, the log is empty again; if the
epoch differs or the file is shorter than `offset`, it was rebuilt or replaced, so the log reloads in full;
otherwise it parses only the complete lines after `offset`, applying the same strict checks as `load`. `_local()`
calls it every time, so `_pending`, `_order_locked`, `notifications`, `max_notification_id`, `_check_tracking` and
`max_tracking_id` all see the file as it is.

Alternative: reload in full only under the write lock. Rejected: reads outside the lock (`max_tracking_id`,
`max_notification_id`) would stay stale, and a full reload is O(file) on every write.

Correctness under the lock: `insert`, `insert_tracking` and `ensure_ordered` take the write lock and then call
`_local()`, so the catch-up happens after any other writer has finished, and the append that follows starts at the
true end of the file. (An extra check that `append_bytes` started at the log's offset was considered and left out.
Every writer appends under the lock, so it couldn't fail without a new error code that nothing could raise.)

### D2. Only a store holding the write lock trims a torn last line
Today `_read_lines` truncates an incomplete last line wherever it's called, including a first load outside the
lock, where the "torn" line may be another writer's append in progress. Reading now takes a `trim` flag: with the
lock held, a torn line is trimmed as before (it never took effect); without it, the incomplete bytes are left alone
and not consumed, and the next catch-up reads them once they're complete.

### D3. Reading notifications outside the lock stays as it is
`ensure_ordered` checks `_pending` without the lock and takes it only when there's something to write; after D1
the check sees the current file, so a reader whose events were already ordered by another store writes nothing.
When it does take the lock, `_order_locked` catches up again before deciding.

### D4. Why a reader writes the order, and why the lock is the one place ids are assigned
The owner asked for the root cause rather than the fix (troupe-run/troupe#450, 2026-11-18). The order log is a
per-clone index that numbers events in the order this clone first sees them (event-store design D5). Events also
arrive with no local writer, from a pull, a merge, or a crash between writing a segment and numbering it. So
whichever store next looks, reader or writer, numbers the visible events that have no id yet, under the write lock
(D10). The lock already makes one store at a time the numberer. The bug is that the numberer worked from a copy of
the log it had loaded earlier: D5 says the store rescans "before every write and read under the lock", and the
code did that for the segments only. D1 makes it do so for the order and tracking logs as well.

A stale copy doesn't only repeat lines. With three stores, the probe for this change got `n=2 E_c, n=3 E_b` from
the writers and then `n=2 E_b, n=3 E_c` from a stale store, so live processes named different events by one id.

**Owner's decision (2026-11-18):** keep D5 as designed: any store may number, under the lock, from the log as it
is now. Rejected: a daemon that alone assigns ids (a long-running process per clone, IPC, crash handling on three
OSes, and it would still have to number pulled events itself), and "only writers number" (pulled events would stay
unnumbered, and unreadable, until the next write).

### D5. Mending order logs this bug already damaged
**Owner's decision (2026-11-18):** repair exact repeats, and rebuild on conflicts.
- **An exact repeat** (a line `{"n": k, "event": e}` where id `k` already names `e`) is dropped. The log is read as
  if the line weren't there. The first store to hold the write lock rewrites the file without the repeats, under
  the same epoch, and reports `events.order-repaired` with how many lines it dropped. The epoch is kept, so
  followers keep their place: every id still names the event it named before.
- **A conflict** is a well-formed line out of sequence: an id that skips ahead, an id that names a different event
  from the one it already names, an event that already has an id, or a second `{"epoch"}` line (a stale store
  starting the order again). This bug can write each of these. Under the write lock the store rebuilds the order from
  the visible events under a new epoch, as for a removed event, and reports `events.order-rebuilt`, whose details
  now name the line and the reason instead of a count of events gone.
- **Anything else** (a line that isn't JSON, or isn't an epoch or `{n, event}` object) is refused as today with
  `events.malformed-record`. This bug never writes it.

A read that finds damage takes the write lock to mend it, the same way `ensure_ordered` takes it to number events.
After a rewrite or a rebuild, every other store sees a different file. A rebuild changes the epoch (D1 reloads). A
repair keeps the epoch, so D1 also checks that the last line it read is still at the same place in the file, and
reloads in full if not.

### D6. A follower when the epoch changes
Followers' positions are recorded per epoch (event-store design D5), and `max_tracking_id` reads only the current
one. After a rebuild a follower's position is gone: it gets "none" and pulls again from id 1, so its projection is
rebuilt and nothing is skipped. Delivery stays at least once. A repair keeps the epoch, so it doesn't affect
followers.
- **A subscriber woken by the store** (`listen`): the subscription compares the order's epoch as well as its
  length, so a rebuild that leaves the length unchanged still wakes listeners, and they read the new order.
- **`troupe logs --follow`** doesn't keep a notification id: on each wake it reads the run again by its sequence
  numbers, so a rebuild changes nothing it shows.
- **The gap that remains:** a follower that pulled notifications under the old epoch, and records a position after
  the rebuild, has that position recorded under the new epoch. The library's `Tracking` carries no epoch, so the
  store can't tell. This was true of every rebuild since event-store D5. No troupe code records positions yet
  (only the recorder contract's suite does), so the gap is raised as troupe-run/troupe#454 rather than fixed here.

### D7. The notices this needs
- New notice `events.order-repaired`, details `{"repeats": <lines dropped>}`.
- `events.order-rebuilt`'s details become one of `{"gone": <count>}` (an ordered event is no longer here, as
  today) or `{"line": <line>, "conflict": <reason>}` (the log named two events by one id, or similar, D5). It's a
  protocol schema change, so the commit is a `fix`, and the generated models and contributing/event-store.md change
  with it.

## Risks / Trade-offs

- [A catch-up on every call adds a `stat` and a small read per store call] → It replaces nothing hot: segment
  refresh already stats the events directory on every call. Measured in the test suite's timing, not assumed.
- [Epoch check reads the first line each time] → One short read; avoids trusting size alone, which can't tell a
  rebuild that grew the file from an append.
- [A store that rebuilds the order while another reads] → `replace_file` is atomic, and the reader sees either the
  old file (then reloads next call) or the new epoch (full reload).
