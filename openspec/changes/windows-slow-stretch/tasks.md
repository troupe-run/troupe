# Tasks

Every temporary edit to `packages/troupe-store-text/src/troupe_store_text/store.py` below is reverted in the same
task, and shown reverted with `git diff --stat` (no change to `store.py`). None of these tasks runs a CPU-load loop.

## 1. Reproduce the slow stretch, without load

- [ ] 1.1 Make a temporary edit that sleeps 0.5 s before the poll branch's `store._deliver()` in `_Subscription._run`.
  Because the test records each event straight after the previous one arrives, every polled delay then sits near
  0.6 s, which is the slow stretch from #91 made repeatable. Run both tests unchanged
  (`uv run pytest packages/troupe-store-text/tests/test_processes.py -k "refused_watch or never_reports"`) and verify
  each fails on its median bound. Keep the edit for 1.2 only, then revert it and show it reverted
- [ ] 1.2 Record which store faults the current tests catch, as the baseline the new tests must match (design,
  Goals). For each of: (a) the poll branch never calls `_deliver()`; (b) the poll branch waits `poll_seconds * 2`;
  (c) the poll branch calls `_deliver()` only on every second look, make the temporary edit, run both tests, and
  record pass or fail for each test. Revert each edit and show it reverted. Verify by the recorded table, whatever it
  shows

## 2. The refused-watch test checks the interval and the next look (design D1, D2, D3, D4)

- [ ] 2.1 Add the recorder (design D2): a `_Subscription` subclass, installed with `monkeypatch.setattr` on the store
  module, whose `_stopped` records each `wait` timeout, and a `_deliver` wrapper that records `(started, delivered)`
  with `time.time()`. Add `polled(store, heard, writer, looks, count=5)`, which records five events as `delays()`
  does (each arrives within 10 s, the order grows by one) and returns each event's append time, its wall-clock delay
  and the index of the look that delivered it. Change `STALL_SECONDS`'s comment to say it also bounds the median of
  polled deliveries (design D4). Leave `delays()` and the watch-wake test unchanged, and verify that test still passes
- [ ] 2.2 Rewrite the refused-watch test to assert, with the recorded waits and looks in each message: at least five
  waits, every one for `poll_seconds`; and for each event, its delivering look started no later than the first look
  that started after its append; and the median delay is under `poll_seconds + STALL_SECONDS` (design D1, check 4).
  Keep its notice assertions. Rename it to
  `test_a_refused_watch_falls_back_to_an_announced_poll_at_its_interval_that_delivers_each_event_at_the_next_look`.
  Verify it passes
- [ ] 2.3 Verify the rewritten test fails against each of 1.2's faults (a), (b) and (c), using the same temporary
  edits, and against (d) a temporary 6 s sleep before the poll branch's `_deliver()`. Under (d) every delivery still
  arrives within the 10 s wait, so verify the failure is the median bound's, which shows check 4 isn't decorative.
  Each edit is reverted and shown reverted. Faults the old test caught must still be caught (design, Goals); (b) and
  (c) must now be caught whatever 1.2 recorded for them
- [ ] 2.4 Re-apply 1.1's 0.5 s sleep and verify the rewritten test passes with it in place. Revert it and show it
  reverted

## 3. The never-reports test's polled deliveries, the same way (design D2, D3)

- [ ] 3.1 Change the never-reports test to use the recorder: its start-up gate waits on the first recorded look
  instead of its own `_deliver` wrapper. After the `events.subscription-polling` notice, replace the median of five
  under `0.2 + BOUND` with the same interval, next-look and loose median assertions as 2.2. Keep the check-delivered event's
  `check_seconds + STALL_SECONDS` bound and the `watch-missed-write` assertion unchanged. Verify it passes
- [ ] 3.2 Verify the changed test fails against 1.2's faults (a), (b) and (c) and 2.3's fault (d), with (d) failing
  on the median bound, and passes with 1.1's 0.5 s sleep in place. Each temporary edit is reverted and shown reverted
- [ ] 3.3 Verify the start-up gate still works (#88 design D6): with a temporary `time.sleep(0.5)` at the top of
  `_Subscription._run`, the test passes. Revert it and show it reverted

## 4. Spec and verification

- [ ] 4.1 Confirm the delta in `specs/event-store/spec.md` states exactly what the changed tests check (each wait is
  for `SUBSCRIBE_POLL_SECONDS`; each of five events is delivered no later than the first look after its append; their
  median delay is within `SUBSCRIBE_POLL_SECONDS` plus an allowance for a loaded machine; the check-delivered event's
  allowance is unchanged), and run `openspec validate windows-slow-stretch --strict`. Verify
  it passes
- [ ] 4.2 Run the whole `test_processes.py` file and `uv run scripts/check.py`. Verify every gate passes, and record
  how the two tests' durations compare with `main`'s
- [ ] 4.3 Open the PR (`Closes #91`) and verify all CI jobs pass on Linux, macOS and Windows. Re-run the Windows job
  twice more and verify it passes each time, recording the run ids in the PR. If #90 is the only failure, record it
  in the PR and re-run; the task isn't ticked until Windows is green

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging, so the PR lands the tests and the synced `event-store` spec
  together.
- After the merge, comment on #91 with the PR and the archived change, and close it.
