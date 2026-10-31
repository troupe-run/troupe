# Tasks

## 1. Find where the time goes

- [ ] 1.1 Instrument the failing test, uncommitted (design D4): wrap the subscription's watch `wait` and `_deliver` to take `time.time()` when the wait returns and when the delivery finishes, and put each delivery's stages in the failure message: append returned, wait returned, delivery finished, and test woke. Verify: `uv run pytest packages/troupe-store-text/tests/test_processes.py -k fastest_under_the_bound` passes locally, and a forced failure (temporarily asserting `min(woken) < 0`) prints the four stages for all five deliveries
- [ ] 1.2 Ask the owner to run the instrumented hunt on Windows under load, or to name a Windows machine for it (this session runs on macOS), with the three tests selected: `uv run scripts/flake_hunt.py --workers 4 --load 4 --rounds 40 packages/troupe-store-text/tests/test_processes.py packages/troupe/tests/test_event_subscription.py packages/troupe/tests/test_platform_watching.py -k fastest_under_the_bound`. Verify: the hunt's report is recorded here, with each failure's stages, or "not reproduced"
- [ ] 1.3 Decide from 1.2's stages, as design D4 lays out: scheduling means go ahead with group 2; the watch itself slow means stop and raise it with the owner (a new issue on the board, per #159's "Not in scope"); not reproduced means ask the owner whether to go ahead on the CI evidence. Verify: the outcome, and the owner's answer where one was needed, recorded here; then revert the instrumentation, and `git status` shows no change outside `openspec/`

## 2. The sampling helper and shared constants

- [ ] 2.1 Write `packages/troupe/tests/test_storetesting.py` with design D3's four cases for `watched_delays` (a scripted `measure`, and a fake clock that advances by each delay): fast first, exactly five; five slow then fast, six; always slow, stops at the budget and never starts a measurement after it, returning every delay; fast within the first five but not first, still five. Verify: `uv run pytest packages/troupe/tests/test_storetesting.py` fails, because `watched_delays` doesn't exist yet
- [ ] 2.2 Add `BOUND`, `STALL_SECONDS`, `SLOW_STRETCH_SECONDS` (60 s) and `watched_delays` to `packages/troupe/tests/storetesting.py` (design D1, D2), with the docstrings D2 describes: `SLOW_STRETCH_SECONDS` cites #159's two all-slow runs, and `STALL_SECONDS` keeps #81, #91 and #100's evidence without the "load doesn't slow every sample" claim. Verify: `uv run pytest packages/troupe/tests/test_storetesting.py` passes, all four cases

## 3. The three tests

- [ ] 3.1 Before changing the tests, make design D5's slow-stretch edit (temporary): every delivery 0.4 s late for the first 8 s after listening, then on time. Put it in `_deliver` for the two store tests, and in the backend's `wait` after a reported change for the raw-watch test. Verify: all three tests fail on unchanged main code with `min(...) < 0.25`, as CI did; record the output here, and keep the edit for 3.3
- [ ] 3.2 Change the three tests to measure through `watched_delays` and import the shared constants, deleting each file's own `BOUND` and `STALL_SECONDS` (design D2): `delays()` in `test_processes.py` wraps the helper; the port test's loop and the raw-watch test's loop become `measure` closures that keep their per-event asserts; each asserts the fastest of all delays is under `BOUND` and the median of the first five under `BOUND + STALL_SECONDS`, with every delay in the message. Verify: without the 3.1 edit, `uv run pytest packages/troupe-store-text/tests/test_processes.py packages/troupe/tests/test_event_subscription.py packages/troupe/tests/test_platform_watching.py` passes
- [ ] 3.3 With the 3.1 edit back in place, run the three tests. Verify: all three pass, each measuring more than five deliveries (shown by a temporary print, or the delays in a forced-failure message); record the counts here
- [ ] 3.4 Make design D5's slow-by-design edit (temporary): every delivery 0.4 s late for the whole test. Verify: all three tests fail once the 60 s budget has passed, each listing every delay; record each test's count and duration here. Then revert both edits, and `git diff` shows only 2.x and 3.2's changes
- [ ] 3.5 Check nothing else defined its own copy: `grep -rn "^BOUND\|^STALL_SECONDS" packages plugins`. Verify: the only definitions are in `storetesting.py`

## 4. Verify

- [ ] 4.1 Run `uv run scripts/check.py`. Verify: every gate passes; record the counts here
- [ ] 4.2 Ask the owner to re-run 1.2's hunt on Windows under load with the fix, without the instrumentation (#159's done-when). Verify: the hunt reports no failures in any round; record its report here

## Workflow follow-up

- Open the PR as a draft with `Closes #159`; CI must pass on Linux, macOS and Windows.
- Act on Claude's review of the last push, then archive the change on the branch (`/opsx:archive`) before merging. The two delta specs (`event-store`, `platform`) sync at archive; no Purpose changes, so no `oob/troupe-spec-purposes.json` update.
- After the merge, comment on #159 with the PR and the archived change, and check its card on the roadmap board says Done.
