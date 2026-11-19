# Design

## Context

See proposal.md for why. The measurement is unchanged from #400 and #407. `_time_after_the_end()` runs 30
interleaved pairs, each a Python child that sleeps `0.020 * i / 30` s, stamps `time.perf_counter()` and exits. It
takes the time from that stamp to the call's return through `subprocess.run` and through `run_to_completion`. A
batch's extra is the difference of the two medians.

- The latency test passes at the first of up to three batches whose extra is under 5 ms (a quarter of the old 20 ms
  tick). So with a tick it fails only when all three batches catch it.
- The power test puts the tick back with a `TickingEvent` whose `wait` sleeps `min(20 ms, timeout)` whatever wakes
  it. It asserts that one batch's extra is at least 5 ms.

With a tick, each run's cost is roughly uniform over 0–20 ms, so it adds about 10 ms to the bounded median. It
fails a batch when that comes out under 5 ms: about 0.27% of batches in #400's binomial model. The failing batch on
#463 had a ticked median of 9.8 ms (about half a tick) against a direct median of 5.2 ms. The direct series on
hosted Windows varies a lot within a batch (#406 saw 4 to 26 ms), so its median takes a bite out of the margin now
and then.

Call **q** the chance that one batch with a tick comes out under the bound on a given leg.

## Goals / Non-Goals

**Goals:**

- An unlucky batch doesn't fail the power check, on Windows or anywhere else.
- The check still fails when the measurement can't see a tick on a platform: when a typical batch misses it.

**Non-Goals:**

- Changing the measurement, the statistic, the bound, the batch size or the latency test. #407's reasons for them
  stand, and the power check has to measure the batch the latency test uses, or it would describe some other test's
  power.
- Changing `run_to_completion`.

## Decisions

### D1: A majority of three batches, stopping as soon as it's decided

The power test measures batches with the tick put back. It passes at the second batch that shows the tick (extra at
least 5 ms) and fails at the second that doesn't. So it measures two batches, or three when the first two disagree.
When it fails, it lists each batch's `measured()`, the same way the latency test does.

- **False failure.** When the measurement sees the tick, a leg fails only if two of three batches are unlucky:
  3q² − 2q³. That's about 0.002% at q = 0.27%, against 0.27% now. Over 12 legs that's about 0.03% of runs, against
  up to about 3% now.
- **What it still catches.** A measurement that's blind to the tick (q near 1) fails on every leg, as now. One that
  misses the tick in half its batches (q = 0.5) fails half the legs, as now. Then the latency test would catch a tick
  on only 1 leg in 8 (0.5³), which is the case this check exists for.
- **Where it is weaker.** At q = 0.2 it fails about 10% of legs, against 20% now. But at q = 0.2 the latency test
  still catches a tick on about half the legs (0.8³ ≈ 0.51), so a tick put back would fail nearly every CI run across
  12 legs (all but about 0.0002%). The property that matters, "a tick put back fails CI", holds well past the point
  where the majority check stops failing.
- **Cost.** Two batches instead of one on a passing run. About 6 s more per leg on Linux and macOS (one batch takes
  5–8 s there today), run in parallel with the rest of the suite. Only a split vote adds a third batch.

*Alternatives:*

- **Keep one batch (#407 D2).** It accepted up to 0.27% a leg, weighing it against 0.8% for "every batch must catch
  it". Counted per run, it's up to about 3%, and #463 shows the queue pays it.
- **Every batch must catch it** (the strict form #407 rejected). This mirrors the latency test exactly, but its false
  failure is 1 − (1 − q)³, about 0.8% a leg.
- **Pass at the first batch that catches it; otherwise both of two more must.** It costs one batch on most runs, and
  its false failure is about 2q². But it's lopsided: at q = 0.5 it fails 37.5% of legs, not 50%. It saves about 6 s
  a leg at the cost of the case the check exists for.
- **More runs in a batch (say 45).** The median gets steadier and q drops, for both tests. But it changes the latency
  test's measurement, which #407 kept as a non-goal, and makes every leg's latency test 1.5 times slower. The power
  check can't use a larger batch on its own, because it has to measure the batch the latency test uses.
- **A lower bound for the power check** (say 4 ms). That passes this failure, but the check would then claim a power
  the latency test, which needs 5 ms, doesn't have.

### D2: The comment says how the two tests relate

The comment drops "checking all of them here would triple this test's own chance of failing" and says three things:

- A tick fails the latency test only when all of its batches catch it.
- This check therefore asks whether a typical batch catches it: a majority of three.
- An unlucky batch must not fail it, because it runs on every leg of every run, the merge queue included
  (troupe-run/troupe#463).

The test's name stays. It still says what it checks: the same measurement tells a 20 ms tick put back.

### D3: How it's checked

Uncommitted patches, each reverted afterwards. The test-side ones change only `TickingEvent` in the power test.

- **A tick the measurement can't see.** `TickingEvent.wait` sleeps 1 ms instead of 20 ms. The check fails, listing
  two batches each under 5 ms.
- **An unlucky first batch.** The tick is skipped for the first 30 bounded calls (a counter on the test's
  `TickingEvent` subclass), so the first batch misses and the next two catch it. The check passes, after three
  batches. The current one-batch check fails with the same patch.
- **A tick that two of three batches miss.** The tick is skipped for the first 60 bounded calls. The check fails
  after three batches.
- **The real tick.** In `run_to_completion`, `output.changed.wait(...)` is replaced by `time.sleep(0.02)`, which is
  #360's regression. The latency test fails in all three batches. The power check passes, because it puts its own
  tick on top.
- **Flake hunt:** `scripts/flake_hunt.py --load 2` on the power test alone, once the 1-minute load average is under
  40. Then check that nothing of this session's is left running. The Windows legs in CI are the real check.

## Risks / Trade-offs

- [Load lasting across two batches on a Windows leg still fails the check] → its message then lists every batch. Two
  batches each just under 5 ms with the tick would mean the margin on that runner is really thin. The next step then
  is Windows samples of the direct series, not a lower bound.
- [The extra 6 s a leg] → the suite runs in parallel, and each leg's wall time is set by its slowest worker, not this
  test. The test-time reports (`--durations=25`) will show it.
