# Tasks

## 1. Reproduce

- [x] 1.1 Ask the owner before the load run, then run the flake hunt on the quiet tests with CPUs kept busy, with timing instrumentation in the run-queries test's failure message (local, uncommitted). Outcome: **not reproduced**. `--load 8 --rounds 40 -k reads_no_segment` (both tests, 1 worker) passed 40 of 40 rounds; `--workers 4 --load 8 --rounds 40` on the whole of both files, for file-system churn, passed 160 of 160 (load average up to 20 on 10 cores). The owner chose to go ahead on the code reading in the proposal, without a captured failure; the instrumentation was reverted

## 2. Fix

- [x] 2.1 In `packages/troupe/tests/test_run_queries.py`, add the bounded waits (design D1–D3): wait until `harness.updates` holds the event with seq 1, then until no look for `SETTLE` (1.5 s, moved to `storetesting.py` from `test_platform_watching.py`, which now imports it), each giving up after 30 s with a message naming the condition; then clear `looks`, wait 2 s and assert `looks == []` as now. Verify: `uv run pytest packages/troupe/tests/test_run_queries.py -k reads_no_segment` passes
- [x] 2.2 In `packages/troupe-store-text/tests/test_processes.py`, replace the fixed 2 s settle in `test_a_listened_store_reads_no_segment_while_nothing_is_recorded` with the same settle-until-quiet wait (design D2, D3). Verify: `uv run pytest packages/troupe-store-text/tests/test_processes.py -k reads_no_segment` passes
- [x] 2.3 Check each test still fails for the defect it's named for: temporarily set `check_seconds` to 0.5 s in both tests, so the store looks at segments every 0.5 s while nothing is recorded, and confirm both tests fail with the settle wait's message; then revert. Verify: both failures seen, and `git diff` shows only the test changes afterwards

## 3. Verify under load

- [x] 3.1 ~~Re-run the hunt from 1.1 after the fix.~~ Dropped with the owner's agreement: the hunt never failed before the fix, so passing after it shows nothing. CI on Linux, macOS and Windows is the check, with the done-when the issue names
- [ ] 3.2 Run `uv run scripts/check.py`, and verify all gates pass

## Workflow follow-up

- Open the PR with `Closes #194`; CI must pass on Linux, macOS and Windows.
- Act on Claude's review of the last push, then archive the change on the branch (`/opsx:archive`) before merging. There are no delta specs to sync.
- After the merge, comment on #194 with the PR and the archived change, and check its card on the roadmap board says Done.
