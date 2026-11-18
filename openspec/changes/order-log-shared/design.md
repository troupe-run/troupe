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
true end of the file. As a check, `OrderLog.append` compares the size `append_bytes` reports with its `offset`; a
mismatch means another writer appended without the lock, which is a bug, so it raises rather than carry on.

### D2. Only a store holding the write lock trims a torn last line
Today `_read_lines` truncates an incomplete last line wherever it's called, including a first load outside the
lock, where the "torn" line may be another writer's append in progress. Reading now takes a `trim` flag: with the
lock held, a torn line is trimmed as before (it never took effect); without it, the incomplete bytes are left alone
and not consumed, and the next catch-up reads them once they're complete.

### D3. Reading notifications outside the lock stays as it is
`ensure_ordered` checks `_pending` without the lock and takes it only when there's something to write; after D1
the check sees the current file, so a reader whose events were already ordered by another store writes nothing.
When it does take the lock, `_order_locked` catches up again before deciding.

### D4. An order log already damaged by duplicate lines (pending the owner's answer)
Clones that ran a reader beside a run may have files with repeated lines (`n=2 e5`, `n=2 e5`). Options asked of
the owner on troupe-run/troupe#450 (through the orchestrator):
- **A (recommended):** while loading, a line that repeats an earlier line exactly (same `n`, same event) is
  dropped, and a store holding the write lock rewrites the file without it (same epoch, so followers' positions
  stay valid), with a notice saying so. Anything else (a different event under a used `n`, a gap) is refused as
  today.
- **B:** refuse as today, with the fix-it message naming this damage; deleting the file rebuilds it under a new
  epoch, and followers start again from the beginning.

This section and the spec delta are updated with the answer before the code depends on it.

## Risks / Trade-offs

- [A catch-up on every call adds a `stat` and a small read per store call] → It replaces nothing hot: segment
  refresh already stats the events directory on every call. Measured in the test suite's timing, not assumed.
- [Epoch check reads the first line each time] → One short read; avoids trusting size alone, which can't tell a
  rebuild that grew the file from an append.
- [A store that rebuilds the order while another reads] → `replace_file` is atomic, and the reader sees either the
  old file (then reloads next call) or the new epoch (full reload).
