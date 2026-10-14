# Proposal

## Why

`test_a_kill_sent_after_the_child_exited_but_before_asyncio_saw_it_did_not_end_it` failed once on Windows, Python
3.13 (#90). It returned `(None, 1953655660, True)` instead of `(None, 0, False)`. 1953655660 is `KILLED_EXIT_CODE`, so
the kill really did end a live child, and `ended_by_kill` was right to say so. The race the test exists to set up
didn't happen.

The test assumes two things it never checks. First, that `_block_until_exited` returned because the child exited. On
Windows and macOS it polls `processes.is_running(pid)` until it reads false **or** 30 s pass, and nothing checks which
happened. On Windows `is_running` also reads false when it can't open the process or read its exit code. Second, that
the child is still running when the test stops yielding to the event loop, which rests on a 0.5 s `time.sleep` in the
child. A loaded runner doesn't have to honour either. When an assumption fails, the test reports it as a wrong
answer about the kill, so a test problem reads like a regression in #87's fix.

The cause on that run is **unconfirmed**. This change doesn't guess at it. It makes the test prove its precondition
and say, by name, which part wasn't reached, so the next failure points at the cause.

## What Changes

- The child exits when the test tells it to, not after a fixed sleep. It says it's running, then waits for a file
  that the test creates only once it has stopped yielding to the event loop. The 0.5 s timing assumption goes.
- The wait for the exit proves the exit and reads the child's own exit status from the operating system, without
  using the seam under test. On Windows that's a handle opened before the exit, waited on, then its exit code read.
  On Linux it's `waitid` without reaping, polled to a deadline rather than blocking with none. On macOS it's the pid
  disappearing once asyncio's watcher thread has reaped it.
- Each precondition that isn't reached fails the test with a message naming it, before anything is asserted about
  the kill: the child didn't exit within the bound, it exited with a status other than 0, or asyncio had already
  seen the exit before the kill.
- Only then does the test kill the child, and assert that its exit code is 0 and the seam says the kill didn't end
  it.
- The fix is checked on Windows CI by running the test 50 times in one job. That runs once before the change, to
  measure how often it fails, and once after. Both repetition commits are reverted before merging.
- No product code changes. `ended_by_kill`, `kill_tree` and `KILLED_EXIT_CODE` are unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. The `platform` scenario "A child that exited before a late kill" already says what the test checks: a child
that has exited with 0, killed before troupe saw the exit, keeps 0 and isn't reported as killed. Only how the test
sets that up and checks it changes, so the change sets `skip_specs: true`.

## Impact

- `packages/troupe/tests/test_platform_processes.py`: `_block_until_exited` is replaced by a helper that proves the
  exit and returns the child's own exit status. The race test's child and its precondition checks change.
- No code, API, protocol, spec or dependency changes. CI must pass on Linux, macOS and Windows.
- Related: #86 (the bug the test was written for), #81 and #91 (other Windows timing assumptions).
