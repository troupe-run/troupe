# Tasks

## 1. Majority of three (D1, D2)

- [ ] 1.1 Before changing the test, apply D3's "unlucky first batch" patch (the tick is skipped for the first 30
  bounded calls) to the current one-batch power test. Verify: it fails. Record the output for the PR.
- [ ] 1.2 Make the power test measure batches with the tick put back until two show it (pass) or two don't (fail),
  failing with every batch's `measured()`. Rewrite its comment as in D2. Verify: it passes 10 times in a row alone
  (`uv run pytest packages/troupe/tests/test_platform_processes.py -k tells_a_20_ms_tick`), and `uv run mypy` on the
  file (with `--platform win32` too) is clean.

## 2. Mutation checks (D3)

- [ ] 2.1 The unlucky first batch from 1.1. Verify: the new check passes after three batches.
- [ ] 2.2 A tick two of three batches miss (skipped for the first 60 bounded calls). Verify: the check fails after
  three batches, listing them.
- [ ] 2.3 A tick the measurement can't see (`TickingEvent.wait` sleeps 1 ms). Verify: the check fails after two
  batches, listing them.
- [ ] 2.4 The real tick: `time.sleep(0.02)` in place of `output.changed.wait(...)` in `run_to_completion`. Verify:
  the latency test fails in all three batches and the power check passes. Revert, and `git diff` shows only the
  intended test change.

## 3. Checks

- [ ] 3.1 Flake hunt on the power test alone, with the orchestrator's go-ahead: check `uptime` (1-minute load under
  40), then `uv run scripts/flake_hunt.py --load 2 -k test_the_time_after_the_end_tells_a_20_ms_tick_put_back
  packages/troupe/tests/test_platform_processes.py`. Verify: no failures, and
  `pgrep -fl "python.*(fake_claude.py|while True: pass)"` shows nothing of this session's afterwards. Record the
  rounds and the load in the PR.
- [ ] 3.2 `uv run scripts/check.py` passes, with the orchestrator's go-ahead (one heavy run at a time), its output
  kept in a scratch file.

## Workflow follow-up

- Draft PR closing #463, act on Claude's review, mark ready, CI green on all three platforms (the Windows legs are
  the real check).
- `/openspec-archive-change` on the branch before the merge.
