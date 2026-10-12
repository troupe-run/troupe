# Proposal

Issue: #43.

## Why

`test_two_processes_racing_for_one_version_give_exactly_one_integrity_error`
(`packages/troupe-store-text/tests/test_processes.py`) failed on Windows, Python 3.12, in PR #42's CI (job
114781179959), on a change that touched no code. The losing racer waited on the store's write lock for longer than
its `lock_announce_after` of 0.1 s, and correctly printed its `on_wait` announcement before its outcome:

```
'waiting C:\\...\\.troupe\\local\\.lock\nintegrity-error'
```

That is the behaviour the event-store spec requires ("Writers wait for each other, bounded and announced": the
waiting process announces the wait). The test reads each child's *whole* stdout as its outcome, so a correct
announcement fails it. It's intermittent: it passed on the other five jobs and on #41's own CI. Until it's fixed,
any PR can fail Windows CI for no reason.

## What Changes

- **A helper reads a child's outcome as its last line of output,** and checks that every earlier line is an
  announcement (`waiting <path>`). Anything else before the outcome still fails, naming the unexpected line.
- **Every place a child's outcome is read uses it:** the racing-writers test (line 87) and the cross-process
  subscription test (line 121), which has the same latent flaw. What each test proves is unchanged: exactly one
  `integrity-error` and one `recorded`, one event in the stream, and the subscription woken by the other process.
- **A test of the helper** uses the real shape from the failing CI run, so the case that failed is covered on every
  platform, not only when a Windows runner happens to be slow.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None: tests only. The event-store spec already requires the announcement; the test was wrong, not the
requirement. The change declares `skip_specs`.

## Impact

- `packages/troupe-store-text/tests/test_processes.py` only. No production code changes.
- Out of scope: `test_a_writer_waiting_for_another_process_announces_it_and_times_out` (line 104), which already
  checks the announcement and the final line separately.
