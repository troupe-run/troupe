# Proposal

Issue: #194.

## Why

`test_following_a_quiet_run_reads_no_segment_while_it_waits` (`packages/troupe/tests/test_run_queries.py`) failed
once in a local `uv run scripts/check.py` on macOS, with the machine loaded (the check took 191 s, not the usual
105 s). It passed 6 of 6 times on its own straight after. The error text wasn't kept.

The test times its quiet window from a fixed 2 s sleep. It assumes that within those 2 s three things have finished,
none of which it checks:

1. **The child has recorded everything it will record.** `HANG` records its init, then a turn, then hangs. `Child`
   returns at the first event, so the turn may be recorded later. On a loaded machine it can land after the 2 s,
   and the follower then rightly wakes and reads.
2. **The follower has made its first read.** It starts in a thread that opens the store, lists the runs, starts
   listening and reads the run. Under load that can run past 2 s, and its first read then counts as a look.
3. **The fresh watch's spurious wakes are over.** FSEvents reports changes made just before a watch started, measured
   at up to 0.49 s afterwards on an idle machine (`5d252a4`). Under load, nothing bounds that by 2 s.

Each of these is a look the requirement allows: the event-store spec's scenario ("The text store does no work while
nothing is recorded") is about a subscriber that waits while **nothing** is recorded, and before the quiet window
starts the test hasn't established that. So the test, not the follower, is wrong: its timing assumes an idle
machine.

The same shape is in `test_a_listened_store_reads_no_segment_while_nothing_is_recorded`
(`packages/troupe-store-text/tests/test_processes.py`): a fixed 2 s settle covers listening's first read and the
watch's spurious wakes (causes 2 and 3). It hasn't failed yet, but it rests on the same assumption, so this change
fixes it too.

## What Changes

- **The quiet window starts from what the test observes, not from a fixed sleep.** The run-queries test first waits
  until the follower has sent the last event the child records before it hangs (the turn), so causes 1 and 2 are
  over. Then both tests wait until the store has made no look for a settle period (cause 3), and only then clear
  the looks and count over the same 2 s window as now. Each wait is bounded, and fails with a message that says
  which condition never came, so a follower that never goes quiet still fails rather than hangs.
- **The assertion is unchanged:** no segment read in 2 s once the store is quiet. A follower that reads while nothing
  is recorded still fails.
- **First, reproduce it under load** and capture the assertion, as the issue asks, so the fix is checked against the
  real failure rather than only the reading above.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None: tests only. The event-store spec's "The text store does no work while nothing is recorded" scenario already
says what the tests check, and the follower's behaviour doesn't change. The change declares `skip_specs`.

## Impact

- `packages/troupe/tests/test_run_queries.py`: the one test, and possibly a small helper beside `follow_in_background`.
- `packages/troupe-store-text/tests/test_processes.py`: the sibling test.
- No production code changes. If reproducing it shows a look while the store really is quiet (a follower that reads
  without a write or a wake), that is a bug in the follower, and the change stops and raises it with the owner
  rather than loosening the test.
