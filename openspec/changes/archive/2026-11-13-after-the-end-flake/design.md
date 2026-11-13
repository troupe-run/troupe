# Design

## Context

See proposal.md for why. The measurement is process-timing-flakes' D2 (archived 2026-11-12): a Python child sleeps
`0.020 * i / 30` s for run `i`, stamps `time.perf_counter()` and calls `os._exit(0)`. The test takes the time from
that stamp to the call's return, through `subprocess.run` and through `run_to_completion`, interleaved, and asserts
the difference of the two medians is under 5 ms (a quarter of the old tick). The ends are spread across one 20 ms
tick, so a tick put back costs each run a roughly uniform 0–20 ms, about 10 ms in the median.

`test_the_time_after_the_end_tells_a_20_ms_tick_put_back` puts a tick back through a ticking `threading.Event` and
asserts the same measurement is at least the bound, so the bound's power is checked on every leg, Windows included.
It hasn't failed.

## Goals / Non-Goals

**Goals:**

- A burst of load during one batch doesn't fail the latency test.
- A tick put back, or any other steady cost after the end of 5 ms or more, still fails it.

**Non-Goals:**

- Changing the measurement, the statistic or the bound. They hold on ~149 of 150 Windows legs, and #400's reasons for
  them stand.
- Changing `run_to_completion`.

## Decisions

### D1: Up to three batches, passing at the first under the bound

`_time_after_the_end()` stays one batch. The latency test calls it up to three times and stops at the first batch
whose extra is under 5 ms. If none is, it fails with each batch's extra and medians.

- **Why it separates the two.** A load burst is transient: on CI it's another test's heavy moment on a shared runner.
  A batch takes a second or two, so the next batch mostly sees different load. A regression is in the code, so it's
  in every batch. Observed per-batch failure on Windows is about 1 in 75; if batches were independent, three in a row
  would be about 1 in 400,000. They won't be fully independent, since load lasts, but the failures so far were single
  batches on otherwise passing legs.
- **What a tick gets away with.** With a tick, a batch passes only if at least 15 of 30 roughly uniform 0–20 ms
  costs land under 5 ms: 0.27% (binomial, ignoring noise). Passing any of three is at most 0.8% per run. A tick that
  came back would be in every leg of every run, so it would fail CI.
- **Cost.** A passing first batch costs what the test costs now. Only a failing batch adds another.
- **The message.** When all three fail, it lists each batch's extra and both medians. A steady cost shows as three
  similar extras; noise shows as scattered ones. That's what #406 couldn't tell from one number.

*Alternatives:*

- **A wider bound**, say 7.5 ms. A tick would then pass a batch about 11% of the time (at least 15 of 30 under
  7.5 ms, each with a 3 in 8 chance). That gives away the test's purpose for one more failure's worth of noise.
- **More runs in one batch** (say 90). The median gets steadier, but a burst that covers the whole batch still moves
  it, and every passing run pays three times the time.
- **A paired statistic** (median of per-pair differences) or a lower quantile. Without Windows samples to compare
  them on, it's a guess whether either has a thinner tail, and the per-batch power #400 worked out would need
  redoing. Re-measuring needs no assumption about the noise's shape, only that it doesn't last.
- **Calibrating against a ticked copy in the same batch** (pass when the real code is nearer the direct series than a
  ticked one). Any steady cost elsewhere in `run_to_completion` would land in both and cancel, so the test would stop
  catching it.

### D2: The power test stays one batch

The latency test with a tick fails only when all three batches are at least the bound. The power test checks one
batch, as now, so its false-failure chance stays 0.27% per leg rather than tripling. The latency test's power is that
per-batch power cubed (about 99.2%), which the docstring states. Its name keeps saying what it checks: one
measurement, the same `_time_after_the_end()` batch, tells a tick.

### D3: How it's checked

Uncommitted patches, each reverted after:

- **A burst, forced:** `run_to_completion` sleeps 8 ms before it returns, for its first 30 calls only (a counter in
  `processes`). The current test fails; the new one passes at its second batch. macOS overshoots the sleep, so it
  measures about 10 ms.
- **A steady delay:** the same sleep on every call. The new test fails, listing three batches each about 10 ms
  over.
- **The tick put back:** `output.changed.wait(...)` in `run_to_completion` replaced by `time.sleep(0.02)` (#360's
  regression). The new test fails in all three batches, run 5 times.
- **Flake hunt:** `scripts/flake_hunt.py --load 2` on the latency test alone, once the 1-minute load average is under
  40, then a check that no load or child processes are left. Windows is where it failed, so CI's Windows legs are the
  real check, and #406 asks for a Windows hunt, which needs the owner's machine.

## Risks / Trade-offs

- [Load lasting across all three batches on Windows fails the test again] → the message then shows three batch
  extras, which tells a steady cost from noise. If that happens with scattered extras, the next step is Windows
  samples to choose a statistic with, not a wider bound.
- [A regression smaller than the bound, or one that only some batches see] → neither was caught reliably before.
  Intermittent extra latency isn't what #360 removed.
