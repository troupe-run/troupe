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
- [x] 4.2 Verify they ride out a 12 s FSEvents stall (a scratch patch holding the first callbacks back): the old three
  fail; the new write-wakes and first-event tests pass, and events-each passes alone (3 of 3). In combination, at load
  40 or more, a delivery was sometimes lost after the stall (3 times in about 20 runs). A standalone probe rules out
  a stream or process that goes deaf. Recorded as a known limit (design, Risks) by owner decision, 2026-11-18

## 5. #452: the quiet tests allow a read on a watch report (design D6)

- [x] 5.1 Add `watch_reports` and `unprompted` to `storetesting.py`; rewrite and rename both quiet tests; verify they
  pass on their own
- [x] 5.2 Mutation-check: with FSEvents callbacks 2 s late the old tests fail and the new pass; with the store also
  reading on a timer (0.5 s, and 1.8 s to get past `settle`) the new tests fail

## 6. Review of 55dc06f7

- [x] 6.1 `WATCH_ONLY_SECONDS` covers the five unconditional measurements (180 s); `STALL_SECONDS`' docstring names no
  single wait; `watch_reports` counts only watches in the test's theatre. Verify the touched tests pass on their own

## 7. "Nothing changes" (design D7)

- [x] 7.1 Wait again after a reported change within the slow-stretch budget; verify the test passes with FSEvents
  callbacks 1.55 to 1.85 s late (6 of 6, against 4 of 9 failing before), and fails with a watch that always reports
  and with one whose quiet wait returns early

## 8. The port test after a fallback to polling (design D8)

- [x] 8.1 Subscribe afresh when the port's notices say the store polls, the restart counting as a notification;
  verify the test passes on its own (3.4 s)
- [x] 8.2 Mutation-check: with FSEvents silent for the first check interval (a scratch patch dropping callbacks for
  31 s), the new test passes after restarting (68.7 s) and c109c49b's fails as the commit check did (29.4 s, then
  about 0.9 s each); a store whose watch is refused still fails

## 9. The raw watch tests' waits (design D9)

- [x] 9.1 Each wait in `test_platform_watching.py` for a report another process's change should cause waits `WITHIN`;
  verify with ruff (the timing runs wait for a quiet machine, 10.1)

## 10. Integration

- [x] 10.1 `uv run scripts/check.py` passes (run when the 1-minute load is under 40): the guard's check of cacb3d78,
  6 workers, load 9 to 18, passed in 317 s

## Workflow follow-up

- Draft PR closing #446 and #448; act on the review; archive on the branch before merge.
