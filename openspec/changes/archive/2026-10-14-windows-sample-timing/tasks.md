# Tasks

## 1. Reproduce the flake before changing anything

- [x] 1.1 Run the two tests on this branch, unchanged, under CPU load (one busy-loop process per core, started from a
  scratchpad script) 20 times each, with `uv run pytest packages/troupe-store-text/tests/test_processes.py -k "refused_watch or never_reports"`.
  Record how many runs failed and the largest delay for the PR. Verify by the recorded counts, whatever they are: a
  failure shows the reproduction, and no failure is recorded as "not reproduced locally" rather than skipped

## 2. The polled deliveries bound a median (design D1, D2, D4)

- [x] 2.1 Add the `delays(store, heard, writer, count=5)` helper (design D2) and use it in
  `test_another_processs_events_each_reach_a_listener_with_a_median_delay_under_the_bound`. Verify that test passes
  unchanged in what it asserts
- [x] 2.2 Change the refused-watch test to bound the median of five polled deliveries under `0.2 + BOUND`, keeping its
  notice assertions, and rename it to
  `test_a_refused_watch_falls_back_to_an_announced_poll_with_a_median_delay_under_the_bound`. Verify it passes, then
  verify it fails against a store whose polling branch never calls `_deliver()` (a temporary edit to `_run`, reverted
  and shown reverted with `git diff --stat`)
- [x] 2.3 Change the never-reports test's post-fallback delivery to the median of five under `0.2 + BOUND`. Verify it
  passes, and fails against the same never-delivering polling branch as 2.2

## 3. The check-delivered event gets a named allowance (design D3)

- [x] 3.1 Add `STALL_SECONDS = 5.0` beside `BOUND`, with a comment giving the reason, and bound the never-reports
  test's first delivery by `check_seconds + STALL_SECONDS`. Verify it passes, and fails against a store whose check
  doesn't deliver (a temporary edit making the check's `_deliver()` a no-op, reverted and shown reverted)

## 4. The never-reports test can't race the subscription's start-up (design D6)

- [x] 4.1 Reproduce the race first: with a temporary `time.sleep(0.5)` at the top of `_Subscription._run`, run the
  never-reports test unchanged and verify it fails waiting for `events.subscription-polling`. Keep the sleep for 4.2
- [x] 4.2 Add the start-up gate (wrap `store._deliver`, wait up to 5 s for its first call to return, before
  `writer.record()`). Verify the test passes with the 0.5 s sleep still in place, then remove the sleep and show it
  removed with `git diff --stat`, and verify the test passes without it

## 5. Spec and verification

- [x] 5.1 Confirm the delta in `specs/event-store/spec.md` states exactly what the changed tests check (median of
  five, `SUBSCRIBE_POLL_SECONDS` plus 0.25 s, the check allowance), and run `openspec validate windows-sample-timing --strict`.
  Verify it passes
- 5.2 (dropped by the owner, 2026-10-14; not a tracked task) Repeat 1.1's loaded runs against the changed tests. It
  ran once: 17 of 20 failed, mostly an event not arriving within the 10 s wait at all. The machine's other load
  (load average 220 to 245, against about 180 during 1.1) starved processes for over 30 s, so the writer couldn't
  even exit in time, in code this change doesn't touch. That's far harsher than the done-when in #81, a loaded CI
  runner, where the stall seen was about 1 s, and the two runs weren't under the same conditions. The CI runs in 5.4
  are the check that matches the issue. Unloaded, the change adds about 1.9 s to the suite (four more events in each
  of the two tests)
- [x] 5.3 Run `uv run scripts/check.py`. Verify every gate passes
- [x] 5.4 Open the PR (`Closes #81`) and verify all CI jobs pass on Linux, macOS and Windows. Re-run the Windows job
  twice more and verify it passes each time, recording the run ids for the PR. #86 currently fails the Windows job
  on `main` (`test_run_host.py`, unrelated to this change). If that is the only failure, record it in the PR and
  rerun once #86 is fixed; the task isn't ticked until Windows is green

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging, so the PR lands the tests and the synced `event-store` spec
  together.
- After the merge, comment on #81 with the PR and the archived change, and close it.
