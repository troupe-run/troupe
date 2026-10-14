# Proposal

## Why

`test_a_refused_watch_falls_back_to_an_announced_poll_with_a_median_delay_under_the_bound` failed on Windows on
`main` at `ee7641b`, straight after #88 replaced its single-sample bound with a median of five (#91). Three of the five
delays were over the 0.45 s bound (0.52, 0.67, 1.01 s), so the median was over too. A median survives one stall, but
not a slow stretch that covers most of the samples. Taking more samples, or spreading them out, only moves the length
of stretch that fails it.

The requirement says the subscription looks every `SUBSCRIBE_POLL_SECONDS` and that each event arrives. A wall-clock
delay measured across two processes and a waking thread adds the machine's load to that, and no bound on it holds on a
loaded runner. The test can instead check those two things directly, in ways load can't change: what interval the
subscription waits between looks, and that each event is delivered by the first look after its append returned. A
loose wall-clock bound stays on top of those, wide enough for a loaded machine, so a store whose looks take seconds
still fails.

`test_a_watch_that_never_reports_is_caught_by_the_check_then_the_store_polls` has the same median assertion on its
polled deliveries after the fallback, so it's exposed to the same slow stretch. This change fixes both, so the issue
doesn't come back under the sibling test's name, as #88 did for #81.

## What Changes

- Both tests stop bounding the wall-clock delay of polled deliveries tightly. Instead they record each look the
  subscription makes while polling, and check:
  - before each look the subscription waits exactly once, for `poll_seconds`, so the store polls at the interval it
    announces;
  - each of five events is delivered by the first look that started after its append returned, or an earlier one
    still in progress, so polling never misses an event it could have seen;
  - each event reaches the listener (the existing 10 s wait) and is the one event the store's order gained;
  - the median delay of the five, from when the append returned, is under `poll_seconds + STALL_SECONDS` (5.2 s
    here), so a store whose looks take seconds still fails.
- `STALL_SECONDS`'s comment changes to say it also bounds the median of polled deliveries, not only single samples.
- The refused-watch test is renamed to say what its body now checks.
- The never-reports test's check-delivered event keeps its single-sample bound (`check_seconds + STALL_SECONDS`), as
  #88 set it. It hasn't failed, and this change leaves it alone.
- The `event-store` spec's two polling scenarios say what the tests now check: the interval the subscription waits,
  delivery at the next look, and a median delay within `SUBSCRIBE_POLL_SECONDS` plus an allowance for a loaded
  machine, in place of the 0.25 s allowance.
- No store code changes. The poll loop and its interval are unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `event-store`: the scenarios of "A subscription that can only poll says so" and "A subscription that finds it
  missed an event says so" state their polling timing as the interval the subscription waits and delivery at the
  next look, with the median wall-clock delay's allowance widened from 0.25 s to one for a loaded machine.

## Impact

- `packages/troupe-store-text/tests/test_processes.py`: the two polling tests, a helper that records the
  subscription's looks, and `STALL_SECONDS`'s comment.
- `openspec/specs/event-store/spec.md`: two requirements' scenarios, through this change's delta.
- No code, API, protocol or dependency changes. CI must pass on Linux, macOS and Windows.
- Out of scope: the three watch-wake tests that bound a median delay under 0.25 s
  (`test_processes.py`, `test_platform_watching.py`, `test_event_subscription.py`). They check how soon a watch wakes
  a subscriber, which is a latency property, and no issue records one failing. If a slow stretch fails one, it needs
  its own issue, as it can't use this change's approach.
