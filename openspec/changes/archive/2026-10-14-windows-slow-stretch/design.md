# Design

## Context

See proposal.md for why. What exists today:

- **The poll loop.** In `_Subscription._run` (`troupe_store_text/store.py`), a subscription with no watch loops on
  `self._stopped.wait(store.poll_seconds)` and, unless it was stopped, calls `store._deliver()`. `_deliver` reads the
  order's length (`max_notification_id()`, which refreshes from the segments) and notifies listeners if it grew.
  A refused watch starts the subscription in this branch; a watch that misses a write switches to it after the check.
- **The two tests** (`packages/troupe-store-text/tests/test_processes.py`) measure each delivery with
  `delays(store, heard, writer)`: wall-clock time from when the `Writer` process's append returned (it prints
  `time.time()`) to when the test thread woke on `heard`. They assert the median of five is under `0.2 + BOUND`
  (0.45 s). That delay covers the remaining poll interval, the read, the notify, the test thread waking, and the
  writer's stdout reaching the test, all of which a loaded machine slows.
- **`delays()` is shared** with the watch-wake test, whose median bound stays as it is.
- **Precedent for wrapping private methods:** the never-reports test already wraps `store._deliver` with
  `monkeypatch`, and `test_a_listened_store_reads_no_segment_while_nothing_is_recorded` wraps `store._sizes`.

## Goals / Non-Goals

**Goals:**
- Each exact assertion in the two tests holds however slow the machine is, as long as every delivery still arrives
  within the existing 10 s wait. The one wall-clock assertion holds through a slow stretch of seconds, far beyond the
  one in #91.
- The tests still fail against a store that never polls, one that polls at an interval other than `poll_seconds`,
  one whose look misses an event that was there to be seen, and one whose looks take seconds.

**Non-Goals:**
- Changing the store, its defaults or its notices.
- The watch-wake median tests (see proposal, Impact).
- Bounding tightly how long one look takes. A store that is a little slow inside a look is indistinguishable, from a
  test, from a slow machine. That is the cost of this approach, recorded under Risks.

## Decisions

### D1: Check the poll's interval and the next-look delivery exactly, and the wall-clock delay loosely

The requirement makes two promises about polling: the subscription looks every `SUBSCRIBE_POLL_SECONDS`, and an event
that's there is found. The tests check each one directly, and keep a loose bound on the delay as a backstop:

1. **Interval.** Before each polled look, the loop waits exactly once, and for `poll_seconds`. This is exact, and
   load can't change it. Checking each wait's timeout alone isn't enough: a loop that skips a look waits twice, each
   time for `poll_seconds`, and every look it does make still delivers at once (found building task 2.3).
2. **Next look.** For each of five events, the look that delivered it started no later than the first look that
   started after the writer's append returned. In other words, no look that started after the event was on disk
   came back empty-handed while the event waited for a later one. A look already in progress when the append
   returned may deliver it, which is allowed. Load stretches the time between looks, but it can't make a look that
   started after the append miss it.
3. **Arrival.** Each event still reaches the listener within the existing 10 s wait, and the order grows by exactly
   one, as `delays()` checks today.
4. **Loose delay.** The median of the five wall-clock delays, from when the append returned, is under
   `poll_seconds + STALL_SECONDS` (5.2 s here). This is the one assertion that measures the machine, so its allowance
   is the same named one #88 gave the check-delivered event: one place says how much a loaded machine may add. #91's
   slow stretch had a median of 0.52 s and a worst sample of 1.01 s, far inside it.

Checks 1 to 3 say exactly what the old median bound was standing in for, and none of them measures the machine.
Check 4 catches what they can't: a store whose looks take seconds, which 1 to 3 pass as long as each look still
finishes inside the 10 s wait.

*Alternative: more samples, or samples spread over time* (the issue's first option). It survives a longer slow
stretch, but there's always a longer one, and the run gets slower for every sample added. Rejected.

*Alternative: bound against a baseline measured in the same run* (the issue's second option), for example a plain
`threading.Event.wait(0.2)`'s overshoot, or a watched delivery's delay. The baseline is measured at a different moment
from the sample, so a slow stretch can cover one and not the other. A baseline from a single thread also misses the
cross-process part of the delay (the writer's stdout, the file reaching the reader). It stays a statistical check
that can flake, with more moving parts. Rejected.

*Alternative: a loosened wall-clock bound alone, in place of checks 1 to 3.* A bound loose enough for a slow stretch
can't tell a 0.2 s poll from a 1 s one, so on its own it no longer checks the interval at all. Rejected as a
replacement. It's kept as check 4, alongside the exact checks, where it only has to catch gross slowness.

*Alternative: checks 1 to 3 without check 4.* Nothing would then bound delivery time on the polled path, and the spec
would stop promising one. Rejected: at 5.2 s, a loose bound adds little risk of flaking.

This is the issue's third option, "keep the absolute bound where it's what we promise ... and only check ordering or
count on the loaded path", with a loose bound kept on the loaded path too. What we promise is the interval, so that's
what gets an exact check.

### D2: One recorder, installed before the subscription starts

A test helper records, for the subscription under test:

- **Looks:** it wraps `store._deliver` (with `monkeypatch`, as the never-reports test already does) to append
  `(started, delivered)` for each call, where `started` is `time.time()` taken before the call, the same clock the
  writer prints, and `delivered` is what `_deliver` returned.
- **Waits:** it installs, with `monkeypatch.setattr` on the store module, a subclass of `_Subscription` whose
  `_stopped` is a `threading.Event` subclass that records, before waiting, how many looks came before the wait and
  its timeout. `listen()` constructs
  `_Subscription` by its module name, so the subclass is in place before the thread starts and every wait is
  recorded, including the first.

Both are installed before `listen()`. The never-reports test's existing `_deliver` wrapper (its start-up gate, #88
design D6) folds into the same recorder: the gate is the first recorded look.

A helper `polled(store, heard, writer, looks, count=5)` records five events like `delays()` does, and returns, per
event, the append time, the wall-clock delay and the index of the look that delivered it. The assertions stay in each test, with the
recorded looks and waits in the failure message, so a failure shows what the subscription actually did.

*Alternative: swap `store._subscription._stopped` after `listen()` returns.* The thread is already waiting by then,
so the first wait goes unrecorded, and the swap races `stop()`. Rejected.

*Alternative: add a clock or sleeper seam to the store.* That changes store code for a test. The behaviour is right,
and the private-method wrapping already has precedent in this file. Rejected.

### D3: Which waits and looks are checked

- **Refused watch:** every wait recorded is a poll wait, so all of them must be `poll_seconds`. Every look from the
  first wait on must have exactly one wait just before it, and there must be at least five such looks (one per
  event), so the check can't pass empty.
- **Never reports:** the silent backend's waits and the store's report-grace wait don't go through `_stopped`, so
  every wait recorded is again a poll wait after the fallback, and the looks from the first wait on are the polled
  ones. Same check. The next-look check and the loose median bound cover only the five events recorded after the
  `events.subscription-polling` notice. The check-delivered event before it keeps its
  `check_seconds + STALL_SECONDS` bound unchanged.

### D4: Names and spec say what the bodies check

- The refused-watch test becomes
  `test_a_refused_watch_falls_back_to_an_announced_poll_at_its_interval_and_delivers_at_next_look`.
  The never-reports test's name doesn't claim a timing and stays.
- The `event-store` scenarios change with the tests (see specs/event-store/spec.md): the wait interval and
  next-look delivery are added, and the median's allowance becomes one for a loaded machine.
- `STALL_SECONDS`'s comment says it bounds the median of polled deliveries too, not only a single delivery.

## Risks / Trade-offs

- [A store that is somewhat slow inside each look, adding up to about 5 s, still passes] → Accepted. From inside a
  test, that looks the same as a slow machine, which is what #91 is about. Looks that take seconds fail check 4. The
  read cost is covered where it's actually specified: `test_a_listened_store_reads_no_segment_while_nothing_is_recorded`,
  and the watch-wake tests' latency bounds.
- [A slow stretch over 5 s could still fail check 4] → It would be five times #91's worst sample. The allowance is
  the one named constant, so CI evidence changes it in one place.
- [The wait check pins the implementation to one `Event.wait` per poll] → If the loop is restructured, the recorder
  sees no waits and the "at least five" assertion fails loudly, rather than passing quietly.
- [Reaching into `_Subscription`, `_stopped` and `_deliver`] → Same trade as the existing `_deliver` and `_sizes`
  wrappers. A rename fails at `monkeypatch.setattr` (which raises on a missing attribute) or at the wait count.
- [Comparing the writer's `time.time()` with the subscription's] → Both read the same system clock on one machine.
  A clock step during the test could misorder them. That's rare, and it would show in the failure message as
  impossible times.

## Migration Plan

None: tests and spec text only. Rollback is reverting the commit.
