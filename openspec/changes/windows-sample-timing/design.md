# Design

## Context

See proposal.md for why. What exists today, in `packages/troupe-store-text/tests/test_processes.py`:

- **`Writer`** runs another process that records one event per line it reads, sleeping 0.1 s first, and reports
  when each segment append returned. Delays are measured from that time, not from the event's `at`.
- **`BOUND = 0.25`** is the median bound the watch-wake tests use. `test_another_processs_events_each_reach_a_listener_with_a_median_delay_under_the_bound`
  records five events, appends each delay to a list, and asserts the median is under `BOUND`.
- **The refused-watch test** uses `poll_seconds=0.2` and a watcher that raises `WatchUnavailableError`, so the
  subscription has no watch and its loop only polls. It records one event and asserts the delay is under
  `0.2 + 1.0`.
- **The never-reports test** uses `poll_seconds=0.2`, `check_seconds=1.0` and a watch that never reports. Its first
  event can only be delivered by the check, which then finds the watch missed it and falls back to polling (after
  `_REPORT_GRACE_SECONDS`, 1 s). It asserts that delay is under `1.0 + 1.0`, waits for the
  `events.subscription-polling` notice, then records one more event and asserts its delay is under `0.2 + 1.0`.

The store's subscription loop (`_Subscription._run` in `troupe_store_text/store.py`) doesn't change.

## Goals / Non-Goals

**Goals:**
- Each timing assertion bounds what its requirement states: that polling delivers at about the poll interval, and
  that the check delivers at about the check interval, rather than never.
- One scheduling stall on a loaded runner can't fail either test, whether it delays a delivery or the subscription
  thread's start.
- Both tests still fail against a store that never polls, and the never-reports test still fails against a store
  whose check doesn't deliver or doesn't fall back.

**Non-Goals:**
- Changing the store, its defaults or its notices.
- Other timing tests in the repository. Only the two that bound a single polled or checked sample are in scope.

## Decisions

### D1: Bound the median of five polled deliveries under `poll_seconds + BOUND`

Both tests record five events while polling and assert the median delay is under `poll_seconds + BOUND` (0.45 s
here). Each delivery waits at most one poll interval, then a read, so the typical delay is about half the interval
plus the read. `BOUND` is the same read allowance the watch-wake tests give a median, so the two families stay
consistent. A median of five survives two stalls of any length.

*Alternative: keep one sample and bound it by a multiple of `poll_seconds`.* A multiple large enough to absorb the
1 s stall seen on Windows (about ×10, 2 s) constrains very little, and would need a separate check that delivery came
from polling. The median keeps a tight bound on the typical delivery without that. Rejected.

*Alternative: keep `0.2 + 1.0` and retry the test on failure.* Retrying hides a real regression as easily as a stall,
and the repository has no retry plugin. Rejected.

### D2: One helper collects the delays

The watch-wake test and both polling tests need the same loop: clear the event, record, wait (10 s), take the delay
from the append, check `max_notification_id()` grew by one. A helper, `delays(store, heard, writer, count=5)`
returning the list, replaces the inline loop in all three, so the way a delay is measured is defined once. Each test
keeps its own `statistics.median(...) < ...` assertion, with the delays in the message, so its bound is visible where
it's checked.

### D3: The check-delivered event stays one sample, with a named stall allowance

The never-reports test's first event can be delivered only by the check, and only once: after it, the store polls.
So it can't be repeated for a median. Its bound becomes `check_seconds + STALL_SECONDS`, a new constant set to 3.0 s,
about three times the largest stall seen, with a comment saying why it's loose. It still sits well inside the 10 s
`heard.wait`, so a store whose check never delivers fails it.

That delivery came from the check, and not from anything else, is shown separately and already asserted: the watch is
silent, polling hasn't started, and the store then announces `events.subscription-polling` with the reason
`watch-missed-write`, which only a check that found an unreported event produces.

### D4: The refused-watch test's name says what it checks

It's renamed to `test_a_refused_watch_falls_back_to_an_announced_poll_with_a_median_delay_under_the_bound`, matching
the watch-wake test's wording. "Still delivers" is true but no longer names the timing the body checks. The
never-reports test's name doesn't mention timing and stays.

### D5: The spec scenarios say the same as the tests

The two scenarios in `event-store` change with the tests (see specs/event-store/spec.md): polled deliveries are a
median of five under `SUBSCRIBE_POLL_SECONDS` plus 0.25 s, measured from the append, and the check-delivered event
is within `SUBSCRIBE_CHECK_SECONDS` plus an allowance for a loaded machine. The figure for that allowance lives in
the test constant, not the spec, as the spec's other scenarios don't fix test tolerances either.

### D6: The never-reports test records only after the subscription's start-up delivery

`_Subscription._run` calls `store._deliver()` once before it waits on the watch. That catches anything recorded
between `start()`'s read and the watch being set up, as
`test_an_event_recorded_while_the_watch_is_being_set_up_reaches_the_listener_at_once` requires. The never-reports
test records its first event straight after `listen` returns, and the writer sleeps only 0.1 s before appending. If
the subscription thread is held back longer than that, the start-up delivery picks up the event. The check then
finds nothing new, `reported` doesn't matter, and the store doesn't fall back. That's correct: a write made before
the watch existed is not one the watch missed. But the test then times out after 5 s waiting for
`events.subscription-polling`.

The test wraps `store._deliver` (with `monkeypatch`) so that it sets a `threading.Event` once its first call returns,
then waits for it (5 s, asserting with a message) after `listen` and before `writer.record()`. With that ordering,
the first event can only arrive through the check. That is what the test means to show, and the
`watch-missed-write` notice then proves it.

*Alternative: sleep after `listen`.* That swaps one timing assumption for another. Rejected.

*Alternative: change the store, so a start-up delivery counts as unreported.* That would be wrong: the watch can't
report a write made before it existed, so the store would fall back on healthy file systems. Rejected. The store's
behaviour is right, and the spec doesn't change for this decision.

## Risks / Trade-offs

- [A median of five can pass while one delivery is badly late] → Accepted: that's the trade the watch-wake tests
  already make. A delivery that never comes still fails, through the 10 s wait.
- [Five events make each test about a second slower] → Accepted. Each record sleeps 0.1 s in the writer and waits at
  most a 0.2 s poll.
- [A stall longer than 3 s at the check could still fail the never-reports test] → The bound is a named constant
  with its reason beside it, so it's one place to change if CI shows it.
- [The start-up gate in D6 reaches into the store's private `_deliver`] → The sibling test
  `test_a_listened_store_reads_no_segment_while_nothing_is_recorded` already wraps `_sizes` the same way. If
  `_deliver` is renamed, the test fails loudly at the monkeypatch rather than passing quietly.

## Migration Plan

None: tests and spec text only. Rollback is reverting the commit.
