# Proposal

## Why

`test_a_refused_watch_falls_back_to_an_announced_poll_that_still_delivers` fails intermittently on Windows (#81). It
bounds the delay of one polled event at `0.2 + 1.0` s, and a single scheduling stall on a shared runner took it to
1.264 s. The requirement it checks is that a refused watch still delivers, at about the poll interval rather than
never. How soon one event arrives on a loaded machine isn't part of that, so the test flakes on something the
requirement doesn't state.

`test_a_watch_that_never_reports_is_caught_by_the_check_then_the_store_polls` has the same shape twice: once for the
event the check delivers (`1.0 + 1.0` s) and once for the event polling delivers after the fallback (`0.2 + 1.0` s).
It hasn't failed yet, but it's exposed to the same stall. It also has a start-up race: the subscription thread
delivers once when it starts, and if a loaded runner holds that thread back past the writer's 0.1 s sleep, that
delivery picks up the test's first event. The check then finds nothing missed, the store rightly doesn't fall back,
and the test times out waiting for a notice that a correct store never gives. This change fixes all three, so the
issue doesn't come back under the sibling test's name. That extends #81's scope by one test, at the owner's request.
It's a different race from #86, which is in the run host.

## What Changes

- The refused-watch test records five events and bounds the **median** delay of the polled deliveries under
  `poll_seconds + 0.25` s, as the sibling wake tests do with their 0.25 s bound. One stall among five no longer fails
  it, and a store that never polls still fails it, because no event arrives at all.
- The never-reports test bounds the median of five polled deliveries after the fallback in the same way.
- The never-reports test's first event can only be delivered by the check, and only once (the store then falls back),
  so it stays one sample. Its bound is loosened to `check_seconds` plus a named stall allowance, with a comment giving
  the reason. That delivery came from the check is already shown separately: the watch is silent, polling hasn't
  started, and the store then announces `events.subscription-polling` with the reason `watch-missed-write`.
- The never-reports test waits until the subscription's start-up delivery has run before it records the event the
  check must find, so that event can only reach the subscriber through the check.
- The `event-store` spec's two polling scenarios say what the tests now check: a median of five deliveries, measured
  from when the writer's append returned.
- No store code changes. The polling and check behaviour is unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `event-store`: the scenarios of "A subscription that can only poll says so" and "A subscription that finds it
  missed an event says so" state their timing as a median over five events, plus a stated allowance for the
  check-delivered event, instead of a bound on one sample.

## Impact

- `packages/troupe-store-text/tests/test_processes.py`: the two tests and one new named constant for the stall
  allowance.
- `openspec/specs/event-store/spec.md`: two requirements' scenarios, through this change's delta.
- No code, API, protocol or dependency changes. CI must pass on Linux, macOS and Windows.
