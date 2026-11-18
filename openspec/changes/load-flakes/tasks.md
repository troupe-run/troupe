# Tasks

## 1. #446: a change between waits, checked with a zero timeout

- [x] 1.1 Rewrite `test_a_change_made_while_nobody_waits_is_reported_by_the_next_wait_at_once` in
  `packages/troupe/tests/test_platform_watching.py` as design D2 says; verify it passes on its own
- [x] 1.2 Verify it rides out late delivery: with the first two backend reports held back past the zero-timeout wait
  (a scratch patch, not committed), the new test passes and the old one fails
- [x] 1.3 Verify it still catches a wait that doesn't report a pending change at once: with a backend whose
  zero-timeout wait never reports (scratch patch, budget shortened to 5 s), the new test fails and the old one passes

## 2. #448: the port test waits as long as the store's backstop

- [x] 2.1 Replace `heard.wait(10)` in `test_event_subscription.py` with the named wait of design D3; verify the test
  passes on its own
- [x] 2.2 Verify the port test now survives one dropped report: with the store's watch dropping one report (scratch
  watcher), the new wait passes and the old 10 s one fails

## 3. The port test's poller claim (design D4)

- [x] 3.1 Count only deliveries a poller couldn't make fast (`Notified`); verify the test passes on its own
- [x] 3.2 Mutation-check against a store whose watch is refused (polls every 1 s): the new test fails with and without
  the writer pausing 0.85 s before each record; the old test passes with the pause

## 4. The watch-only tests in `test_processes.py` (design D5)

- [x] 4.1 Give the three tests `HEARD_WITHIN` and `WATCH_ONLY_SECONDS`; verify they pass on their own
- [ ] 4.2 Verify they ride out a 12 s FSEvents stall (a scratch patch holding the first callbacks back): the new tests
  pass and the old ones fail. So far: the old three fail; the new write-wakes and first-event tests pass; the new
  events-each test passes alone (3 of 3) but twice in 14 runs after write-wakes got no delivery at all within 30 s
  once the stalled callback returned (the writer's next record was never reported). Not a stream or process that
  goes deaf: a standalone probe with two 12 s blocked callbacks, then a fresh stream, heard every later write. Open
  until that is explained.

## 5. #452: the quiet tests allow a read on a watch report (design D6)

- [x] 5.1 Add `watch_reports` and `unprompted` to `storetesting.py`; rewrite and rename both quiet tests; verify they
  pass on their own
- [x] 5.2 Mutation-check: with FSEvents callbacks 2 s late the old tests fail and the new pass; with the store also
  reading on a timer (0.5 s, and 1.8 s to get past `settle`) the new tests fail

## 6. Integration

- [ ] 6.1 `uv run scripts/check.py` passes (run when the 1-minute load is under 40)

## Workflow follow-up

- Draft PR closing #446 and #448; act on the review; archive on the branch before merge.
