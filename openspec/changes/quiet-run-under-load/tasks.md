# Tasks

## 1. Reproduce

- [ ] 1.1 Ask the owner before the load run. Then run the flake hunt on the two quiet tests with CPUs kept busy, e.g. `uv run scripts/flake_hunt.py --load <cpus> --rounds <n> -k "reads_no_segment" packages/troupe/tests/test_run_queries.py packages/troupe-store-text/tests/test_processes.py`, and keep each failure's full assertion. Temporarily record, in the run-queries test's failure message, when each look came relative to the follower sending seq 1 (a local, uncommitted change). Verify: at least one failure is captured, and its looks fit cause 1, 2 or 3 of the proposal. If none fails in a reasonable budget, or a captured look fits none of them, stop and report to the owner with the hunt's output before going on

## 2. Fix

- [ ] 2.1 In `packages/troupe/tests/test_run_queries.py`, add the bounded waits (design D1–D3): wait until `harness.updates` holds the event with seq 1, then until no look for `SETTLE` (1.5 s, docstring pointing at `test_platform_watching.py`'s), each giving up after 30 s with a message naming the condition; then clear `looks`, wait 2 s and assert `looks == []` as now. Verify: `uv run pytest packages/troupe/tests/test_run_queries.py -k reads_no_segment` passes
- [ ] 2.2 In `packages/troupe-store-text/tests/test_processes.py`, replace the fixed 2 s settle in `test_a_listened_store_reads_no_segment_while_nothing_is_recorded` with the same settle-until-quiet wait (design D2, D3). Verify: `uv run pytest packages/troupe-store-text/tests/test_processes.py -k reads_no_segment` passes
- [ ] 2.3 Check each test still fails for the defect it's named for: temporarily make the follower (or the store's subscription) look at segments every 0.5 s while nothing is recorded, and confirm both tests fail with the settle wait's message; then revert. Verify: both failures seen, and `git diff` shows only the test changes afterwards

## 3. Verify under load

- [ ] 3.1 With the owner's go-ahead, re-run the hunt from 1.1 with the same load and at least as many rounds. Verify: no failure, and record the rounds, load and timings in the PR description
- [ ] 3.2 Run `uv run scripts/check.py`, and verify all gates pass

## Workflow follow-up

- Open the PR with `Closes #194`; CI must pass on Linux, macOS and Windows.
- Act on Claude's review of the last push, then archive the change on the branch (`/opsx:archive`) before merging. There are no delta specs to sync.
- After the merge, comment on #194 with the PR and the archived change, and check its card on the roadmap board says Done.
