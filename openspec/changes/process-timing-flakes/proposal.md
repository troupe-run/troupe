# Proposal: the run-to-completion timing tests pin the tick without racing the machine

## Why

Two tests that #367 (git-call-latency) added to `packages/troupe/tests/test_platform_processes.py` fail now and then
on loaded machines. They've dropped #379, #384 and #390 from the merge queue on Windows legs, and #379 (21k lines)
still has to get through it.

- **troupe-run/troupe#395.** `test_every_wait_runs_to_the_next_deadline_and_none_is_a_fixed_tick[passes its output
  limit]` asserts that at least one bounded wait was made. The child writes 200,000 bytes at once. If the drain
  threads pass the 100,000-byte limit before the main thread reaches its loop, `run_to_completion` kills the child and
  raises `OutputTooLargeError` at its first overflow check, without waiting at all. That's correct behaviour, and the
  test fails with "no bounded wait was made".
- **troupe-run/troupe#398.** `test_a_command_that_exits_at_once_costs_about_what_starting_it_directly_costs` asserts
  that the median of 20 `git --version` runs through `run_to_completion`, minus the median of 20 started directly, is
  under 10 ms. Each median is 55–90 ms on a loaded runner, and most of that is process start-up, which load moves by
  more than 10 ms. It failed at 11.0 ms on Windows (Python 3.15) and 12.7 ms on macOS. The bound is also weak where
  it matters: when git takes longer than the old 20 ms tick, a tick's cost depends on where git's exit falls between
  two ticks, so its median is about 10 ms, and a tick that came back would pass about half the time.

## What Changes

- **The output-limit case passes its limit only after the first wait has started.** The child waits for a gate file
  before it writes. The test's recorder opens the gate when `run_to_completion` makes its first wait, bounded or not.
  So the overflow always comes after a wait the test has recorded, and the test still checks every recorded wait
  against the next deadline. If a fixed tick or an unbounded wait came back, the case would still fail (design D1).
- **The latency test measures from the command's end to the result, not from its start.** The command is a Python
  child that writes `time.perf_counter()` as it exits. The test takes the time from that stamp to the moment the call
  returns, both through `run_to_completion` and through `subprocess.run`, interleaved. Process start-up, which is
  where the load noise is, is no longer part of the measurement. The children end at times spread evenly across one
  old 20 ms tick, so a tick that came back would cost about 10 ms in the median, wherever the machine's start-up time
  falls. The bound is 5 ms over the direct median (design D2).
- **Both fixes are checked against the regressions they guard.** A 20 ms tick put back into `run_to_completion`
  fails both tests. The old output-limit case fails when the main thread is held before its loop, and the new one
  doesn't. A flake hunt under light load runs each test on its own (design D3).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. `run_to_completion` already behaves as the `platform` spec's "A command run to completion returns as soon as
it has ended" says. This changes two tests only, so the change sets `skip_specs`.

## Impact

- `packages/troupe/tests/test_platform_processes.py`: `_record_the_waits` and `_OVERFLOWS` (the gate),
  `test_every_wait_runs_to_the_next_deadline_and_none_is_a_fixed_tick`, and the latency test, which is renamed for
  what it checks.
- No product code changes. `troupe.platform.processes` is untouched.
