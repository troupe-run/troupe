# Proposal: the after-the-end latency test re-measures before it fails

## Why

troupe-run/troupe#406. `test_a_command_returns_as_soon_after_it_ends_as_one_started_directly` (from #400, for #398)
dropped #403 from the merge queue twice, both on Windows legs under the full suite's load:

| Run | Leg | Measured |
|---|---|---|
| 43337245162 | windows-latest, Python 3.15 | 6.7 ms over (medians of 30: 16.3 ms against 9.5 ms) |
| 43348966704 | windows-latest, Python 3.13 | 7.0 ms over (medians of 30: 19.4 ms against 12.4 ms) |

The bound is 5 ms. These are the only two failures of the test in the ~60 CI runs since #400 merged (2026-11-12),
which ran it on about 150 Windows legs and passed the rest. So it isn't a steady Windows cost of
`run_to_completion`: it's the tail of a measurement taken during a burst of load, about 1 batch in 75 on Windows.

#400 already took start-up out of the measurement. What's left, the time from the child's exit to the call's return,
is scheduling, and a loaded Windows runner moves it by more than 5 ms now and then. That can't be measured away. But
it differs from what the test guards against in one way that can be used: a load burst passes, and a regression
doesn't. A 20 ms tick put back costs about 10 ms in the median of every batch, on every run.

## What Changes

- **The latency test measures up to three batches and passes at the first one under the bound.** Each batch is the
  same 30 interleaved runs each way, the same statistic (difference of medians) and the same 5 ms bound as now. A
  second and third batch run only when the one before failed, so a passing run costs what it does now. When all three
  fail, the message gives every batch's medians, so a real failure shows whether it was steady or noisy (design D1).
- **The power test still checks one batch.** `test_the_time_after_the_end_tells_a_20_ms_tick_put_back` keeps
  asserting that one batch with a 20 ms tick put back is at least the bound, on every leg. The latency test fails
  with a tick only if all three batches catch it, so its power follows from the per-batch power this test checks
  (design D2).
- **Checked against a regression and against a burst.** A 20 ms tick put back in `run_to_completion` must fail the
  latency test in all three batches. A delay that only the first batch sees, standing in for a load burst, must fail
  the old test and pass the new one (design D3).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. `run_to_completion` already behaves as the `platform` spec's "A command run to completion returns as soon as
it has ended" says. This changes tests only, so the change sets `skip_specs`.

## Impact

- `packages/troupe/tests/test_platform_processes.py`: `_time_after_the_end` and its result type, the latency test,
  and the power test's use of them.
- No product code changes. `troupe.platform.processes` is untouched.
