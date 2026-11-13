# Tasks

## 1. Re-measure before failing (D1, D2)

- [ ] 1.1 Force a burst on the current test: an uncommitted patch delays `run_to_completion`'s return by 8 ms for
  its first 30 calls in the test process. Verify: the current latency test fails with about 8 ms over. Record the
  output for the PR.
- [ ] 1.2 Make the latency test measure up to three batches with `_time_after_the_end()`, passing at the first whose
  extra is under 5 ms and failing with every batch's extra and medians. Leave the power test on one batch, and say in
  its docstring how the two powers relate. Verify: it passes 10 times in a row alone, and with 1.1's patch it passes
  too.

## 2. Still catches a regression (D3)

- [ ] 2.1 Make 1.1's 8 ms delay apply to every call. Verify: the latency test fails, listing three batches each
  about 8 ms over.
- [ ] 2.2 Put the 20 ms tick back as `time.sleep(0.02)` in place of `output.changed.wait(...)`. Verify: the latency
  test fails in all three batches on each of 5 runs; the power test passes.

## 3. Checks

- [ ] 3.1 Flake hunt on the latency test alone: check `uptime` (1-minute load under 40), then
  `uv run scripts/flake_hunt.py --load 2 -k test_a_command_returns_as_soon_after_it_ends_as_one_started_directly
  packages/troupe/tests/test_platform_processes.py`. Verify: no failures, and
  `pgrep -fl "python.*(fake_claude.py|while True: pass)"` shows nothing of this session's afterwards. Record rounds
  and load in the PR.
- [ ] 3.2 `uv run scripts/check.py` passes, its output kept in a scratch file.

## Workflow follow-up

- Draft PR closing #406, act on Claude's review, mark ready, CI green on all three platforms (the Windows legs are the
  real check).
- `/opsx:archive` on the branch before the merge.
