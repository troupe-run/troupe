# Design

## Context

See proposal.md for why. What exists today:

- **Three tests, one shape.** Each measures five deliveries by wall clock, from when another process's write returned
  (it prints `time.time()`) to when the test thread woke, then asserts `min(delays) < BOUND` (0.25 s) and
  `median(delays) < BOUND + STALL_SECONDS` (5.25 s):
  - `test_another_processs_events_each_reach_a_listener_the_fastest_under_the_bound`
    (`packages/troupe-store-text/tests/test_processes.py`, through `delays()`), with poll and check at 60 s, so every
    delivery inside the 10 s wait is the watch's. This is the one that failed.
  - `test_another_writers_events_reach_a_port_subscriber_the_fastest_under_the_bound`
    (`packages/troupe/tests/test_event_subscription.py`), the same through the port with the store's defaults.
  - `test_another_processs_appends_each_wake_a_wait_the_fastest_under_the_bound`
    (`packages/troupe/tests/test_platform_watching.py`), the raw `DirectoryWatch`.
- **Three copies of the constants.** Each file defines `BOUND = 0.25` and `STALL_SECONDS = 5.0`. Two docstrings say
  "load doesn't slow every sample (the fastest in those runs took 0.08 s and 0.12 s)". `storetesting.py` already holds
  shared timing (`SETTLE`), and `test_platform_watching.py` already imports from it.
- **History.** #100 went from one sample to a median of five (`7b01ab5`), then to exact poll checks for the polled path
  (`e16c065`, windows-slow-stretch), then to "fastest under the bound, median loose" for watched deliveries
  (`c0aadf4`). windows-slow-stretch rejected "more samples" because there's always a longer slow stretch and every
  added sample slows the run. Neither objection holds against an adaptive count (D1).
- **What a delivery's delay is made of.** On the store path: the OS signalling the change, the subscription thread
  waking from `WaitForMultipleObjects`, `_deliver` taking the store's lock and reading the segment, setting the
  listener's event, and the test thread waking. Only the first part is the watch. The rest is scheduling and one small
  read, which a loaded two-core runner slows.

## Goals / Non-Goals

**Goals:**
- None of the three tests fails from a slow stretch shorter than the budget, however many deliveries it covers.
- Each still fails against a watch that never reports promptly. That covers a watch slowed by design (a coalescing
  latency, say), one that only wakes on its timeout, and a subscription that only delivers on its check.
- A quiet machine runs exactly what it runs today: five deliveries.
- One place says how long the bound is, how much a loaded machine may add to a median, and how long a slow stretch
  the tests ride out.

**Non-Goals:**
- Changing the watch, the subscription, their defaults or notices. If the instrumented hunt (D4) shows the OS side
  itself is slow on Windows, that's a finding for the owner and a new issue, not part of this change.
- A load-independent measure of the watch's own latency. Windows' change notifications carry no timestamp, so from a
  test the OS's share of a delay can't be separated from the waiting thread's scheduling.
- The polled-delivery tests, which windows-slow-stretch already made exact.

## Decisions

### D1: Sample until one delivery is fast, within a slow-stretch budget

The fastest-of-N check is right in kind. A watch that is slow by design is slow every time, while load is uneven
over time. What failed is N fixed at five, which spans only one to seven seconds. So N becomes adaptive:

1. Measure five deliveries, as now.
2. While no delay so far is under `BOUND`, and less than `SLOW_STRETCH_SECONDS` (60 s) has passed since the first
   measurement started, measure one more.
3. The test asserts the fastest of all the delays measured is under `BOUND`, and the median of the **first five** is
   under `BOUND + STALL_SECONDS`, as now.

The budget is checked before each extra measurement, and each measurement keeps its own 10 s wait, so a failing run
ends within about 70 s. A quiet machine stops after five, as today. A loaded one measures until the stretch passes. The
longest stretch seen so far covered about 7 s of deliveries (the first failure: five delays adding up to 6.8 s). The
other xdist worker's property test, the likely load, ran for 56 s. 60 s covers both.

The median stays on the first five so that it measures the same thing it does today. Taken over every delivery, a
long slow run would sample mostly slow ones, which is exactly what the extra measurements are there to get past.

*Alternative: a larger fixed N* (the issue's first example). To cover 60 s it would need about 50 deliveries on
every run, quiet ones included. That's the slow run windows-slow-stretch rejected. Rejected.

*Alternative: a bound tied to the platform's watch mechanism* (the issue's second example), say a per-platform
`BOUND`, or a same-moment baseline such as a pipe write sent alongside each append. A per-platform bound would loosen
Windows' guarantee to fit a loaded runner, though the spec promises 0.25 s on every platform. A paired baseline
crosses fewer thread hops than a delivery does: the subscription thread, the store's lock and the read are extra, and
each hop costs a scheduling slice under load. So the difference still flakes, with more moving parts. Rejected.

*Alternative: exact checks only, as windows-slow-stretch did for polling.* With poll and check at 60 s, "only the
watch could have delivered it" already holds. What the bound adds is promptness, and promptness is a wall-clock
property. Rejected as a replacement. The watch-only argument stays in the test's comment.

### D2: One helper and one set of constants, in `storetesting.py`

`storetesting.py` gains `BOUND`, `STALL_SECONDS`, `SLOW_STRETCH_SECONDS` and a helper:

```python
def watched_delays(
    measure: Callable[[], float],
    *,
    clock: Callable[[], float] = time.monotonic,
    slow_stretch: float = SLOW_STRETCH_SECONDS,
) -> list[float]:
    """Each delay ``measure`` returns: five, then one at a time while none is under BOUND, until
    ``slow_stretch`` seconds have passed since the first started (design D1)."""
```

Each test passes a closure that records one event and returns its delay, keeping its own per-event asserts (the
order grew by one, `heard.wait(10)`). `delays()` in `test_processes.py` becomes a thin wrapper over the helper. The
assertions stay in each test, with every delay in the failure message, so a test's name and body still match. The
names claim "the fastest under the bound", and that is still what the body checks.

The three files import the constants instead of defining them. One docstring, on `SLOW_STRETCH_SECONDS`, records the
evidence: #159's two runs, every sample slow. `STALL_SECONDS`' docstring keeps #81, #91 and #100's evidence and drops
"load doesn't slow every sample". `test_processes.py`'s `STALL_SECONDS` also bounds polled and check-delivered events,
with the same value. Those uses import the shared one and are otherwise unchanged.

*Alternative: keep per-file constants.* Three copies of one decision, and two of them already carry a claim that has
since been disproved. Rejected (one decision, one place).

### D3: The helper is tested without a machine

A new `packages/troupe/tests/test_storetesting.py` drives `watched_delays` with a scripted `measure` and a fake clock
that advances by each scripted delay:

- A fast first delivery: exactly five measured.
- Five slow, then a fast one: six measured, stopping at the fast one.
- Always slow: measuring stops once the budget has passed, never starts one after it, and every delay is returned.
- A fast delivery in the first five that isn't the first: still exactly five, because the count never drops below
  five.

These pin the stopping rule, which the three real tests can only exercise on a loaded machine.

### D4: Find where the time goes before fixing, on Windows under load

The fix assumes the slow deliveries are scheduling, not the watch. Before building it, an instrumented hunt
(uncommitted) times each stage of every delivery in the failing test: the append returned, the subscription's watch
wait returned, `_deliver` finished, and the test thread woke. Each slow delivery's share then shows in the failure
message. It runs through `scripts/flake_hunt.py` on Windows, under load, with the three tests selected, and needs
a Windows machine. This session runs on macOS, so the owner runs it, or names a machine for it. The owner is
asked before any load run.

- Most of the time between the wait returning and the test waking, or between the append and the wait returning only
  while the machine is loaded: scheduling. Go ahead with D1.
- The append-to-wake gap slow even with no load, or showing a floor near or above 0.25 s: the watch. Stop and raise
  it with the owner, per the issue's "Not in scope".
- No failure reproduced: record that, and ask the owner whether to go ahead on the CI evidence, as with
  quiet-run-under-load.

### D5: Show each test still fails for what it's named for

Two temporary edits, each reverted:

- **A slow stretch** (load the fix must survive): delay every delivery by 0.4 s for the first 8 s after listening,
  covering the first five, then none. On the old check this fails, as CI did. With the fix it passes, measuring more
  than five. This is the differential check, old against new, on the same edit.
- **A watch slow by design** (what the tests must still catch): delay every delivery by 0.4 s for the whole test. With
  the fix it fails once the budget runs out, listing every delay.

For the raw-watch test, the delay goes in the backend's `wait` after a change is reported. For the two store tests,
it goes in the subscription's `_deliver`.

## Risks / Trade-offs

- [A slow stretch longer than 60 s still fails] → It would be about ten times the longer of the two seen. The budget
  is one named constant, so new CI evidence changes it in one place.
- [A broken watch now takes about 70 s to fail instead of a few] → It only costs time on a failing run, and the
  failure lists every delay.
- [A watch that is fast only now and then, say one delivery in twenty, passes on a loaded machine] → Accepted. On a
  quiet machine it measures five and fails unless one of the first five is fast. The median on the first five also
  still bounds gross slowness.
- [The extra measurements add load of their own, a process writing and a thread reading] → One event at a time with
  a 0.1 s writer pause, as today. That's negligible next to the load that triggers them.
- [The fake clock in D3 doesn't prove the real one is read correctly] → The helper calls `time.monotonic` by default,
  and D5's slow-by-design run checks the real budget end to end.

## Migration Plan

None: tests and spec text only. Rollback is reverting the commits.

## Open Questions

- The budget's value. 60 s is chosen from the evidence above. If the owner wants a shorter failing run, or a longer
  ride-out, it changes in one place without changing the approach.
