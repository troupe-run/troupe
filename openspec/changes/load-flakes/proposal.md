# Proposal

## Why

Timing tests fail on a loaded Mac (1-minute load 18 to 65 on 10 cores) and pass alone:

- #446: `test_a_change_made_while_nobody_waits_is_reported_by_the_next_wait_at_once` timed the next wait with the
  wall clock and failed when it took 0.32 s against a 0.25 s bound.
- #448: `test_another_writers_events_reach_a_port_subscriber_the_fastest_under_the_bound` failed at
  `assert heard.wait(10)`: no delivery at all within 10 s of the writer being asked to record.
- #452: `test_following_a_quiet_run_reads_no_segment_while_it_waits` read a segment in its 2 s quiet window, twice in
  four full checks on this branch.

Neither is a lost wake-up in troupe (design D1, D3). Each test asserts something the code doesn't promise under load:
#446 measures a property ("the wait doesn't block") with a clock that load also stretches, and #448 waits less for one
delivery than the store's own backstop for a report the OS drops or delays.

## What Changes

- **#446:** the test checks "at once" without a clock. After the change and a quiet half second, a wait with a zero
  timeout must report it. Load can only make the OS deliver later; when it hasn't delivered yet, a normal wait must
  still report the change (it's never lost), and the test tries again, up to the 60 s slow-stretch budget the other
  watched-delivery tests use. A backend that blocks, or only notices changes while someone waits, still fails every
  time.
- **#448:** the port test's wait for each delivery covers the store's designed backstop
  (`SUBSCRIBE_CHECK_SECONDS` plus `STALL_SECONDS`), named, instead of a bare 10 s. The test's properties are unchanged:
  the fastest delivery under 0.25 s proves the watch, and a store that never delivers still fails.
- **The port test's "a store that only polls can't pass"** becomes true: a delivery counts towards the bound only if
  its event was recorded soon enough after the last notification that a poller couldn't be under it. Before, a writer
  that paused before recording let a polling-only store pass.
- **The three watch-only tests in `test_processes.py`**, which failed the same way in this branch's own commit check,
  wait up to 30 s per delivery, with the poll and check set past the test's whole length (120 s) so only the watch
  can deliver.
- **#452, the two quiet tests** (following a quiet run, and a listened text store) allow a read that follows a watch
  report, made late by the OS for an earlier change, and still fail any read with no report since the last one: a
  read on a timer. They're renamed to say so.
- The platform spec's "A change between waits is kept" scenario, the event-store spec's delivery and quiet scenarios,
  and the runs spec's "Nothing is recorded while following" scenario say what the tests now check.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `platform`: "A directory can be watched for changes": the "A change between waits is kept" scenario says the next
  wait reports the change even with a zero timeout, once the OS has delivered it.
- `event-store`: "A subscription delivers other writers' events as they're recorded": the watch-only scenario's
  intervals are past the test's length, and the port scenario's fastest delay is among deliveries a poller couldn't
  make fast; the quiet scenario allows a read that follows a watch report.
- `runs`: "Following subscribes to the store's events": the "Nothing is recorded while following" scenario allows a
  read that follows a watch report, never one on a timer.

## Impact

Tests only: `packages/troupe/tests/test_platform_watching.py`, `test_event_subscription.py`, `test_run_queries.py` and
`storetesting.py`, and `packages/troupe-store-text/tests/test_processes.py`.
No runtime code changes. Found on the way, filed separately and not part of this change: #450 (two stores on one theatre append the same notification ids).
