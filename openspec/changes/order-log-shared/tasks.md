# Tasks

## 1. Failing tests from the issue's repro

- [x] 1.1 Add a test where two store instances on one theatre take turns inserting and reading (the #450 repro),
  then a fresh store loads the order; verify it fails on main with "expected notification id"
- [x] 1.2 Add the three-store probe (a stale store gives one id to different events) as a test; verify it fails on
  main
- [x] 1.3 Add the same across two processes (a child process records while this one reads), and a tracking test
  where a second store records a position that isn't greater than one another store recorded; verify both fail on
  main

## 2. Catch the local logs up with their files (design D1, D2)

- [x] 2.1 Give `OrderLog` and `TrackingLog` an offset and `catch_up()` (full reload when the epoch changed, the file
  shrank or vanished; otherwise parse only new complete lines); verify unit tests for append-by-another, rebuild,
  deletion and a torn tail
- [x] 2.2 Trim a torn last line only when the caller holds the write lock; verify a test that a reader outside the
  lock leaves a part-written line in place and reads it once complete
- [x] 2.3 Call `catch_up()` from `TextStore._local()` (design D1; the size check in `OrderLog.append` was considered
  and left out, D1); verify the tests from group 1 pass, and the existing store tests
  (`packages/troupe-store-text/tests`, `test_event_subscription.py`) still pass

## 3. Mend already-damaged order logs (design D5 to D7, owner's decision 2026-11-18)

- [x] 3.1 Add `events.order-repaired` and the `{line, conflict}` form of `events.order-rebuilt`'s details to
  `protocol/schemas/notice.schema.json` (and its packaged copy) and `troupe.core.notices`; verify the protocol schema
  tests pass
- [x] 3.2 Drop exact repeats on read and rewrite the file under the same epoch with the notice; verify a test that a
  file with the #450 damage loads, keeps its epoch and followers' positions, and no longer has the repeats
- [x] 3.3 Rebuild the order under a new epoch on a conflict, with the notice naming the line; verify tests for each
  conflict shape (one id for two events, an event with two ids, a gap, a second epoch line)
- [x] 3.4 Detect a file rewritten under the same epoch (D5) in `catch_up`; verify a test where one store repairs
  while another has read past the repeats
- [x] 3.5 Wake listeners when the epoch changes (D6); verify a test of a follower mid-stream across a rebuild (it
  gets no position and pulls from 1) and of a listener woken by a same-length rebuild
- [x] 3.6 Update contributing/event-store.md (the new notice, the rebuilt notice's details, mending); verify the
  docs reference check passes
- [x] 3.7 Raise the follow-up issue for D6's remaining gap (a position recorded after a rebuild for notifications
  read before it), on the board

## 4. Integration

- [ ] 4.1 Run `uv run scripts/check.py` and verify it passes

## Workflow follow-up

- Archive the change after Claude's review of the last push is clean.
- After the merge, check #450 is closed and its card says Done.
