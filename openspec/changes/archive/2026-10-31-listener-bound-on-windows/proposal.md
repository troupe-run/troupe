# Proposal

## Why

`test_another_processs_events_each_reach_a_listener_the_fastest_under_the_bound` has failed twice on Windows CI
(#159): once on PR #158's run (Python 3.12, delays 0.78 s to 2.17 s) and once on `main` after #201 (Python 3.14,
0.38 s to 0.82 s). Both times **every** one of the five deliveries missed the 0.25 s bound, and a re-run passed. The
check rests on a claim #100 wrote into the tests: "load doesn't slow every sample", so the fastest of five lands in a
quiet moment. Both failures disprove it. Five deliveries take one to seven seconds, and a slow stretch on a loaded
runner (here, another xdist worker's 56 s git property test) can cover all of them.

Two sibling tests make the same check on the same claim and haven't failed yet:
`test_another_processs_appends_each_wake_a_wait_the_fastest_under_the_bound` (the raw watch, platform spec) and
`test_another_writers_events_reach_a_port_subscriber_the_fastest_under_the_bound` (the store through the port). The
issue's done-when, "can't fail from runner load alone while still failing when the watch doesn't deliver promptly",
applies to all three, so this change fixes all three.

## What Changes

- The three watched-delivery tests keep measuring five deliveries. If none is under the bound, they keep measuring
  more, one at a time, until one is or a named budget for a slow stretch (60 s) runs out. A watch that is slow by
  design is slow every time and still fails, once the budget is spent. A loaded runner fails only if its slow stretch
  outlasts the budget, about ten times the longer of the two observed. On a quiet machine nothing changes: five
  deliveries, the first under the bound.
- The median check stays, on the first five deliveries, with its existing allowance.
- `BOUND`, `STALL_SECONDS` and the new budget move to one place (`packages/troupe/tests/storetesting.py`), with the
  sampling helper. Today each test file defines its own copy, and two of the three docstrings repeat the claim the
  failures disproved.
- The helper gets its own tests, which run against a scripted sequence of delays and a fake clock rather than a
  machine.
- Before the fix, an instrumented flake hunt on Windows under load splits each slow delivery into its parts: until
  the watch woke, until the read finished, and until the listener woke. That shows whether the time goes to
  scheduling, as the issue expects, or to the watch itself.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `event-store`: in "A subscription delivers other writers' events as they're recorded", the scenarios "Another
  process records events" and "The same guarantee through the port" say the fastest delivery is under 0.25 s among
  the first five, or among more recorded until one is or the slow-stretch budget runs out. The median stays on the
  first five.
- `platform`: in "A directory can be watched for changes", the scenario "Another process appends to a file" changes
  the same way.

## Impact

- Tests only: `packages/troupe-store-text/tests/test_processes.py`, `packages/troupe/tests/test_platform_watching.py`,
  `packages/troupe/tests/test_event_subscription.py`, and `packages/troupe/tests/storetesting.py`, plus a new test
  file for the helper.
- No change to the watch, the subscription, their defaults or notices. If the hunt shows the watch itself is slow on
  Windows, that is outside this change, and goes to the owner as a new issue (the issue's "Not in scope").
- A test that fails because a watch really is slow now takes up to about 70 s to fail, rather than a few seconds.
  A passing run on a quiet machine takes as long as it does today.
- No spec is added or removed, and no Purpose changes, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json`
  needs no update.
