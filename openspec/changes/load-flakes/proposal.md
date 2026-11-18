# Proposal

## Why

Two timing tests fail on a loaded Mac (1-minute load 18 to 65 on 10 cores) and pass alone:

- #446: `test_a_change_made_while_nobody_waits_is_reported_by_the_next_wait_at_once` timed the next wait with the
  wall clock and failed when it took 0.32 s against a 0.25 s bound.
- #448: `test_another_writers_events_reach_a_port_subscriber_the_fastest_under_the_bound` failed at
  `assert heard.wait(10)`: no delivery at all within 10 s of the writer being asked to record.

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
- A new text-store test pins that backstop down deterministically: when the watch drops one report after reporting
  others, the next check delivers the event, and the store keeps watching.
- The platform spec's "A change between waits is kept" scenario says what the test now checks.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `platform`: "A directory can be watched for changes": the "A change between waits is kept" scenario says the next
  wait reports the change even with a zero timeout, once the OS has delivered it.

## Impact

Tests only: `packages/troupe/tests/test_platform_watching.py`, `packages/troupe/tests/test_event_subscription.py`,
`packages/troupe-store-text/tests/test_processes.py`. No runtime code changes. Found on the way, filed separately and
not part of this change: #450 (two stores on one theatre append the same notification ids).
