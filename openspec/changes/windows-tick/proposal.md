# Proposal: the tick put-back check judges by a majority of three batches

## Why

troupe-run/troupe#463. `test_the_time_after_the_end_tells_a_20_ms_tick_put_back` failed in the merge queue on hosted
Windows (Python 3.14, run 44437096329) and dropped #462, which doesn't touch `troupe.platform`:

```text
with a 20 ms tick put back, run_to_completion returned later after the command ended than subprocess.run did by
4.6 ms (medians of 30: 9.8 ms against 5.2 ms): the bound wouldn't catch the tick
```

It's the only failure of this test in any of the 46 failed CI runs since #407 merged (2026-11-13), so it isn't a
steady Windows blind spot. It's the tail #407 chose to keep. #407's design D2 kept this check at one batch because
the only multi-batch form it weighed, "every batch must catch the tick", would triple the check's own chance of
failing on an unlucky batch (about 0.27% per batch with a tick, from #400's binomial model). That reasoning holds
for that form, but it misses two things:

- **The cost is per CI run, not per leg.** The check runs on 12 legs in every pull-request run and every merge-queue
  run. At up to 0.27% a leg, that's up to about 3% of runs, and a failure in the queue drops someone else's pull
  request.
- **More than one batch doesn't have to mean a stricter test.** Judging by a majority of three batches lowers the
  false-failure chance to about 3 × 0.27%² (0.002% a leg) instead of tripling it. It still fails whenever a typical
  batch misses the tick, which is when the latency test would miss it too.

## What Changes

- **The power check measures up to three batches with a tick put back and goes with the majority.** It passes once
  two batches show the tick (extra at least 5 ms), and fails once two don't. The batch, the statistic and the bound
  are the same as now. When it fails, the message gives every batch's extra and medians, the same as the latency
  test's (design D1).
- **Its comment says why**, in place of #407's reasoning: how a majority relates to the latency test's power, and
  what a per-run false-failure rate costs (design D2).
- **Mutation-checked:** a tick the measurement can't see fails the check; a tick that only the first batch misses
  passes it; a tick that two of three batches miss fails it; the real tick put back in `run_to_completion` still
  fails the latency test and passes this check (design D3).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This changes a test only; `run_to_completion` already does what the `platform` spec says. The change sets
`skip_specs`.

## Impact

- `packages/troupe/tests/test_platform_processes.py`: the power test and its comment. The latency test and
  `_time_after_the_end()` are unchanged.
- The power test usually runs two batches instead of one: about 6 s more per leg on Linux and macOS, run in parallel
  with the rest of the suite.
