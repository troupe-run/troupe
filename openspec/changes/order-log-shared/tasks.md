# Tasks

## 1. Failing tests from the issue's repro

- [ ] 1.1 Add a test where two store instances on one theatre take turns inserting and reading (the #450 repro),
  then a fresh store loads the order; verify it fails on main with "expected notification id"
- [ ] 1.2 Add the same across two processes (a child process records while this one reads), and a tracking test
  where a second store records a position that isn't greater than one another store recorded; verify both fail on
  main

## 2. Catch the local logs up with their files (design D1, D2)

- [ ] 2.1 Give `OrderLog` and `TrackingLog` an offset and `catch_up()` (full reload when the epoch changed, the file
  shrank or vanished; otherwise parse only new complete lines); verify unit tests for append-by-another, rebuild,
  deletion and a torn tail
- [ ] 2.2 Trim a torn last line only when the caller holds the write lock; verify a test that a reader outside the
  lock leaves a part-written line in place and reads it once complete
- [ ] 2.3 Call `catch_up()` from `TextStore._local()` and check `append_bytes`'s size against the offset in
  `OrderLog.append`; verify the tests from group 1 pass, and the existing store tests
  (`packages/troupe-store-text/tests`, `test_event_subscription.py`) still pass

## 3. Already-damaged order logs (design D4, after the owner's answer)

- [ ] 3.1 Implement the owner's choice (repair exact duplicates with a notice, or refuse with a fix-it naming this
  damage), update the design and the spec delta to match; verify a test loading a file with the #450 damage

## 4. Integration

- [ ] 4.1 Run `uv run scripts/check.py` and verify it passes

## Workflow follow-up

- Archive the change after Claude's review of the last push is clean.
- After the merge, check #450 is closed and its card says Done.
