# Design

## Context

See proposal.md, Why. What exists today, in `packages/troupe/tests/test_platform_processes.py`:

- **The race test** starts `python -c "import time; time.sleep(0.5)"`, then, without awaiting anything, calls
  `_block_until_exited(child.pid)`, reads `child.returncode`, calls `kill_tree()`, awaits `wait()` and asserts
  `(seen, exit_code, ended_by_kill) == (None, 0, False)`. All three are checked in one tuple, so a race that wasn't
  set up and a seam that answered wrongly fail the same way.
- **`_block_until_exited`**: on Linux, `os.waitid(P_PID, pid, WEXITED | WNOWAIT)` with no timeout, and a
  `ChildProcessError` (a watcher thread reaped it first) suppressed. Elsewhere, it polls `processes.is_running(pid)`
  every 10 ms until it reads false or 30 s pass. It returns `None` either way.
- **`processes.is_running` on Windows** returns false when `OpenProcess` fails, when `GetExitCodeProcess` fails, or
  when the exit code isn't `STILL_ACTIVE`. Only the last means the process exited.
- **The seam** (`ChildProcess.kill_tree`, `ended_by_kill`, `KILLED_EXIT_CODE`) is what the test checks, and it
  doesn't change.
- On Windows, CI runs the child through the venv's `python.exe`, a launcher that starts the real interpreter as its
  own child and exits with that interpreter's exit code. `child.pid` is the launcher. That's what asyncio waits on
  and what `ended_by_kill` is given an exit code for, so it's also what the test must watch.

Why the race didn't happen on #89's run is unconfirmed. The candidates the helper can't tell apart today are: the
30 s deadline passed, `is_running` read false without the child having exited, or the child exited before the test
blocked the loop (which would have failed differently, with `seen == 0`, so it wasn't this one).

## Goals / Non-Goals

**Goals:**
- The test reaches the race's precondition by the order of its own actions, not by a sleep. The child can't exit
  before the test has stopped yielding to the event loop.
- Each part of the precondition is proven before the kill, using the operating system directly, not the seam under
  test. A part that isn't reached fails the test with a message saying which one.
- No wait in the test is unbounded.
- The test still fails against a seam whose `ended_by_kill` ignores the exit code (true whenever a kill was sent).
  That's the regression #87 fixed.

**Non-Goals:**
- Changing `processes.is_running`. On Windows it reads false when it can't open the process, where POSIX reads true
  on a permission error. That's a seam ambiguity in its own right, and it could explain #90. But no product code uses
  `is_running`, only tests, and this change stops relying on it. It's tracked as #92, not changed here.
- The documented Windows limitation that a process the child starts before the job is assigned escapes the job
  (docs/platform.md). With the venv launcher, that can include the real interpreter. It doesn't affect this test,
  which kills a child that has already exited.
- Other timing tests (#81, #91).

## Decisions

### D1: The child exits when the test creates a file, not after a sleep

The child is `python -c CODE PATH`. It prints `up`, then polls every 10 ms for `PATH` to exist, for at most 10 s. It
exits 0 when the file appears, or 3 if it never does. 10 s sits well inside the test's 30 s bound (D2), so a child
that's never told ends with its own code before the test gives up on it. The test awaits the `up` line, so asyncio has started the child
and the child is running. It then stops awaiting and creates the file from the test's own thread. From that point the
loop can't run, so asyncio can't record the exit, however long the child takes to see the file.

*Alternative: write a line to the child's stdin.* `StreamWriter.write` happens to start the write at once on both
loop implementations, but that's asyncio's internals, and closing stdin only takes effect on the loop. A file is
created synchronously by the test, with no loop involved. Chosen.

*Alternative: keep the sleep and make it longer.* That's still a timing assumption, only a looser one. Rejected.

### D2: `_wait_for_exit` proves the exit at the OS level, and returns the child's own status

A new helper replaces `_block_until_exited`. It waits up to `EXIT_BOUND_SECONDS` (30 s, a named constant) and returns
the exit status the operating system recorded for `child.pid`, or `None` where the platform has already given that
status to asyncio's watcher. It calls `pytest.fail` if the child hasn't exited in time. Per platform:

- **Windows**: the test opens a handle to `child.pid` with `SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION` through
  `ctypes`, **before** it creates the file, while the child is known to be running. The handle pins that process, so
  a reused pid can't stand in for it. The helper calls `WaitForSingleObject(handle, bound)`. `WAIT_OBJECT_0` means it
  exited, and `GetExitCodeProcess` gives its code. `WAIT_TIMEOUT` fails as "not exited within the bound". A failure
  of any call fails with the Windows error. Nothing is inferred from a call that couldn't run.
- **Linux**: `os.waitid(P_PID, pid, WEXITED | WNOWAIT | WNOHANG)`, polled every 10 ms to the bound. It leaves the
  child unreaped for asyncio. A result with `si_code == CLD_EXITED` gives `si_status`. A `ChildProcessError` means a
  watcher thread reaped it, which proves the exit, and returns `None`. This replaces today's blocking call, which
  had no bound.
- **macOS**: asyncio's watcher thread reaps the child with `waitpid` and can only *schedule* the returncode on the
  blocked loop. So `os.kill(pid, 0)` raising `ProcessLookupError` proves the child exited and was reaped. The helper
  polls that to the bound and returns `None`. It calls `os.kill` directly rather than `processes.is_running`, to stay
  independent of the seam.

*Alternative: keep polling `processes.is_running`, then check the deadline.* That tells "timed out" apart from
"read false", but on Windows "read false" still includes "couldn't open the process". The handle wait is a
single, unambiguous answer. Rejected.

*Alternative: add an exit-status function to the seam.* No product code needs one. The test's precondition should
be observed independently of the code under test, and Linux's only non-reaping way is `waitid` on one's own child,
which doesn't generalise. Rejected. The `ctypes` declarations live in the test module, beside the helper, behind
`if WINDOWS`.

### D3: The precondition is checked in parts, and the kill is asserted only after

In order, with no await between creating the file and `kill_tree()`:

1. After `up`: `child.returncode is None`.
2. `_wait_for_exit` returns (D2), or fails with "the child did not exit within 30 s".
3. `child.returncode is None` still. Otherwise fail with "asyncio saw the exit before the kill, so the race was not
   set up".
4. `kill_tree()`, then `await child.wait()` with a 30 s timeout.
5. The child's own status is `0`. Otherwise fail with "the child exited with N before the kill, not 0". A 3 here
   means it never saw the file. Where the OS gave a status (Windows, and Linux unless a watcher thread reaped the
   child), that's the one read before the kill. Where it gave `None`, the child was reaped before the kill, so the
   code `wait()` returns is its own, and the kill couldn't have changed it. That's why this check comes after the
   wait: on macOS the status can't be read any earlier.
6. Assert `(exit_code, ended_by_kill) == (0, False)`.

Every precondition failure starts with `precondition not reached:`, so in a CI log it can't be mistaken for the
seam answering wrongly. They fail rather than skip, as #90 asks: a skipped race test would quietly stop testing the
race.

The test's name stays. It already says what the body checks.

### D4: The test is run 50 times on Windows CI, before and after

The repository has no `pytest-repeat`, and adding a dependency to measure once isn't worth it. A temporary commit
parametrizes the test over `range(50)`. It's pushed once on the unchanged test, to measure how often it fails, and
once on the changed test, then reverted in its own commit. Every repetition commit says why it's there. The runs'
ids and results go in the PR. CI runs both Python 3.12 and 3.13 on `windows-latest`, so each push gives 100 runs on
Windows.

## Risks / Trade-offs

- [The unchanged test may not fail in 50 × 2 runs, so "before" doesn't reproduce #90] → Recorded as "not
  reproduced", with the counts. The change doesn't depend on reproducing it. It makes any recurrence name its cause.
- [After the change, a run fails with a precondition message] → That's the diagnosis #90 asked for, not a pass. The
  task isn't ticked. The message goes to the owner with the run id, and if it implicates `is_running` or the launcher,
  that becomes its own issue.
- [The Windows `ctypes` declarations duplicate a few of the seam's] → Accepted. The test needs `WaitForSingleObject`,
  which the seam doesn't declare, and sharing declarations with the code under test would weaken the check.
- [The child polls for the file every 10 ms] → Bounded at 10 s, and it ends with its own distinct code (3), so it
  can't hang or pass by accident.

## Migration Plan

None: one test module only. Rollback is reverting the commit.
