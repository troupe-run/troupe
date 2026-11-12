# Design

## Context

See proposal.md for why. Both tests pin git-call-latency's D2 ("How the latency is pinned in tests"):

- `_record_the_waits` swaps the `threading`, `subprocess` and `time` modules that `troupe.platform.processes` uses
  for recording stand-ins. Every `Event.wait` and `Popen.wait` timeout is recorded, and `time.sleep` fails the test.
- `run_to_completion`'s loop checks for overflow before anything else, then waits either on `output.changed` or, once
  both streams have ended, on `process.wait`, each bounded by the next deadline.
- The latency test times `git --version` from start to result: 20 runs each way, interleaved, compared by median.

Measured here (macOS, 2026-11-12, 20 runs per series): timed from the child's end, `run_to_completion` and
`subprocess.run` differ by about 0.1 ms in the median at idle and by at most 1.2 ms at load average ~200. With the
20 ms tick put back (the change event's `wait` sleeps 20 ms instead), the difference was 7.5–15.3 ms over 12 series.
Timed from start with git, the same tick cost 15–18 ms locally, where git takes less than one tick, but on Windows,
where git takes 55–90 ms, a tick's cost depends on where git's exit falls between ticks.

## Goals / Non-Goals

**Goals:**

- Neither test depends on which of two threads gets scheduled first, or on how long processes take to start.
- Each still fails if `run_to_completion` goes back to a fixed polling tick (#360's regression).

**Non-Goals:**

- Changing `run_to_completion`. It behaves as the `platform` spec says.
- The other cases of the bounded-wait test. "Ends at once" always waits, in `process.wait` if not on the event.
  "Announced then ends" and "passes its timeout" can't finish without waiting.

## Decisions

### D1: The output-limit child writes only once the first wait has started

`_OVERFLOWS` becomes a template with a gate path. The child polls for the gate file every 5 ms. Once it exists, the
child writes 200,000 bytes and then sleeps for 60 s, as now. If the gate doesn't appear within 20 s, the child exits
without writing, so a broken loop fails the test (`DID NOT RAISE OutputTooLargeError`) instead of hanging it.

`_record_the_waits` takes an optional `on_first_wait`. The recording `Event.wait` and `Popen.wait` call it once, after
recording the call and before waiting, whether or not the wait has a timeout. The test passes a function that creates
the gate file under `tmp_path`. So:

- The overflow can only happen after `run_to_completion` has made a wait, and that wait has been recorded. "No
  bounded wait was made" can then only mean the wait was unbounded, which is the failure it should report.
- A fixed tick that came back would be recorded as the first wait (20 ms asked for, with 30 s left), and the check
  against the next deadline fails it. A `time.sleep` tick still fails at once.
- An unbounded wait also opens the gate. The overflow sets the event, the loop raises, and the test fails on "no
  bounded wait was made", instead of hanging.

The case still checks that no announcement was made and that it took under 10 s. The overflow happens a few
milliseconds after the first wait starts.

*Alternatives:* drop the "at least one bounded wait" assertion for this case, as #395 suggested. Then the case would
pass on a run that never waits, so it would prove nothing about ticks on the runs that race. A child that sleeps
before writing would only make the race rarer. The gate makes the order certain.

### D2: The latency test measures from the command's end, with ends spread across one tick

The command is `python -c` with code that sleeps `0.020 * i / N` s for run `i` of `N`, writes `repr(time.perf_counter())`
to stdout, flushes, and calls `os._exit(0)`. For each run, the test reads the stamp from the result and takes
`time.perf_counter() - stamp` straight after the call returns. Runs alternate between `subprocess.run` (capture
output, the same env) and `run_to_completion`.

- **From the end, not the start.** A tick costs time only after the command ends, between its exit and the next
  check. Start-up is what load moves, and it's identical in both paths, so leaving it out removes the noise and keeps
  the signal. `os._exit` keeps interpreter teardown out of it as well.
- **Ends spread across one tick.** With a tick, the cost of a run is the time from its end to the next tick. That
  depends on how long the command took modulo 20 ms. Spreading the sleeps evenly across 20 ms makes those costs about
  evenly spread from 0 to 20 ms, a median of about 10 ms, on any machine.
- **`N = 30`, bound 5 ms over the direct median.** For a tick to pass, half of 30 roughly uniform costs would have to
  land under 5 ms, where each has a 1 in 4 chance: about 0.2% of runs. Without a tick, the difference measured is
  about 0.1 ms idle and under 1.5 ms at load ~200. 60 Python starts take 2–3 s locally, about as long as 40 git
  starts on Windows.
- **The same clock.** `time.perf_counter` is `CLOCK_MONOTONIC` on Linux, `mach_absolute_time` on macOS and
  `QueryPerformanceCounter` on Windows, all system-wide, so a child's stamp can be compared with the parent's clock.
  The test checks every direct latency is at least 0, with a message saying the child's clock isn't the test's,
  so a platform where this stops holding fails clearly rather than measuring nonsense.
- **The name says what it checks:** `test_a_command_returns_as_soon_after_it_ends_as_one_started_directly`.

*Alternatives:* a bound relative to the direct median, more git runs, or the minimum of each series (#398's
suggestions). All three still time start-up. A relative bound gets looser as start-up gets slower, so on Windows it
would let the tick through. The minimum of a series with a tick can land just after a tick and cost nearly nothing.
More runs make the median steadier but don't move the tick's median cost of about 10 ms on slow starts away from the
bound.

### D3: How the fixes are checked

- **Tick put back:** an uncommitted patch replaces `output.changed.wait(...)` in `run_to_completion` with
  `time.sleep(0.02)`, #360's regression. Both tests must fail, the output-limit case on the sleep and the latency
  test on its bound. Then a second patch makes the event's wait `output.changed.wait(0.02)`. The output-limit case
  must fail on the 20 ms asked for. The latency test passes with this one, and should: the wait still returns as soon
  as the output ends, so it costs no time after the command ends. It only wakes the waiting thread every 20 ms, which
  is what the bounded-wait test is for.
- **The old race, forced:** an uncommitted stand-in for `processes.time.monotonic` sleeps 0.5 s on the call that
  starts the loop's clock. The old output-limit case fails with "no bounded wait was made". The new one passes,
  because the child can't write before the first wait.
- **Flake hunt:** `scripts/flake_hunt.py --load 2` on each test alone, one hunt at a time, started only when the
  1-minute load average is under 40, then a check that no load or child processes are left. The final runs are on
  CI's three platforms, where the queue failures happened.

## Risks / Trade-offs

- [A Windows runner's `perf_counter` isn't shared between processes] → the sanity check fails with a message naming
  it. Windows documents QPC as system-wide, so it isn't expected.
- [The gate's file poll costs up to 5 ms after the first wait] → only in the output-limit case, which has a 10 s
  bound.
- [The latency test now starts Python, not git] → `run_to_completion` doesn't care which command it runs. The cost
  the spec's scenario talks about is the time after the command ends, which this measures directly.
