# Design

## Context

See proposal.md, "Why", for the three things the fixed 2 s sleep assumes have finished. The relevant mechanics:

- `logs(follow=True)` (`troupe.core.runs.queries.logs`) listens, reads the run once, sends its events, then waits on
  the store's wake for up to `LOGS_LEASE_CHECK_SECONDS` (1 s). A timeout checks the lease without reading a
  segment. Only a wake reads the run again, and so calls the recorder's `_sizes`, which the test counts.
- With `QUIET` (`poll_seconds` and `check_seconds` both 60), only a watch notification can wake the follower within
  the test's bounds. A notification comes from a real write or an FSEvents spurious wake.
- `Harness.send` appends each update to `harness.updates`, so the test can see which events the follower has sent.
- `HANG` records seq 0 (init) and seq 1 (the turn), then hangs without recording anything else.

## Goals / Non-Goals

**Goals:**
- Both quiet tests pass on a loaded machine, and still fail when a store reads a segment while nothing is recorded
  and nothing has woken it.
- Every wait the tests add is bounded and names what it waited for when it gives up.

**Non-Goals:**
- No change to the follower, the store's subscription or the watch. FSEvents' late spurious wakes are allowed by the
  platform spec ("A spurious True is allowed").
- No change to the 2 s quiet window the spec's scenario names.

## Decisions

### D1: Wait for the follower to have sent the child's last event

Before settling, the run-queries test waits until `harness.updates` holds the event with seq 1, the turn `HANG`
records before it hangs. That ends causes 1 and 2 together: the child has nothing left to record, and the follower
has read the run since its last write.

- *Alternative: wait for the child to announce its hang* (a new `TROUPE_TEST_STOP` point in `perform_child.py`).
  That covers cause 1 only. The follower can still be mid-start, and it adds a hook for one test.
- *Alternative: a longer sleep.* It moves the threshold rather than removing it, and slows every run.

### D2: Settle until no look for `SETTLE` seconds, then count

Both tests then wait until no look has happened for a settle period, by polling the `looks` list the tests already
keep: the clock restarts at each look. Only then do they clear `looks` and count over 2 s. The settle period is
1.5 s, the value `test_platform_watching.py`'s `SETTLE` already used for spurious wakes. Both test packages already
import `packages/troupe/tests/storetesting.py`, so `SETTLE` moves there with the two waits (`wait_until`, `settle`), and
the watch tests import it: one named place for the value.

- *Alternative: drain the watch directly*, as `settled()` does in the watch tests. The follower's watch lives inside
  the store and the follower's thread, so the test can't reach it without reaching into internals.

### D3: Bound each wait at 30 s, with a message

The waits from D1 and D2 give up after 30 s and fail with which condition never came ("the follower never sent seq 1",
"the store never went 1.5 s without a look"). 30 s is well past the 18 s the slowest of the issue's solo runs took, and keeps
the test from hanging (there is no per-test timeout, and the config says never wait silently or indefinitely). A
store that reads segments constantly fails D2's wait, so the test still catches the defect it's named for, with a
message that says so.

## Risks / Trade-offs

- [Settling until quiet could hide a store that reads segments regularly but more slowly than every 1.5 s] → The
  2 s window that follows still catches anything at least once every 2 s, as now. Polling at the `QUIET` intervals
  (60 s) was never in the window's reach, before or after.
- [The reading in "Why" could be wrong, and the failure come from something else] → Task 1.1 tried to reproduce the
  failure under load first. It didn't reproduce in 200 loaded runs, and the owner chose to go ahead on the code
  reading. The fix doesn't depend on which of causes 1–3 it was, and task 2.3 shows the tests still catch a store
  that keeps reading.
- [Reproducing it loads the machine] → Ask the owner before the load run, per the standing preference.
