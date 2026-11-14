# Proposal: an interrupted flake campaign always stops

## Why

`test_an_interrupted_campaign_stops_its_hunt_runs_no_more_and_reports` failed once (troupe-run/troupe#358, macOS 3.13,
merge-queue run 42811183434). The hunt stopped 0.9 s after the interrupt and wrote its summary, but
`scripts/flake_campaign.py` didn't exit. #372 (archived change `2026-11-11-slow-runner-flakes`) gave the test more time
and a stack dump, but left the cause unknown.

The cause is in how the campaign takes Ctrl-C. Python's default handler raises `KeyboardInterrupt` wherever the main
thread happens to be. The campaign spends nearly all its time in `subprocess.Popen.wait(timeout)`. On POSIX that call
takes the process's private `_waitpid_lock` with `acquire(False)`, then enters the `try` whose `finally` releases it.
If the interrupt lands just after the acquire and before the `try`, the exception leaves the lock held for good. From
then on `poll()` reports "still running" (it gives up when it can't get the lock), so the campaign waits its full 60 s
`STOP_WAIT_SECONDS` for a hunt that has already exited. Then `kill()` and `wait()` with no timeout block on the lock
for ever. That matches the failure. The window is a few bytecodes long, which is why the failure is rare, and a loaded
runner makes it likelier. Forcing a real `SIGINT` at that point hangs today's campaign every time (design D1).

## What Changes

- **The campaign takes Ctrl-C as a stop request, not an exception.** While it runs, `SIGINT` (and `SIGBREAK` on
  Windows) only sets a flag. The campaign checks the flag in its wait on a hunt and between hunts, so no exception
  can land inside `subprocess`'s own code. A stopped hunt still gets `STOP_WAIT_SECONDS` to write its summary. Then
  no more hunts run, and the report marks the campaign stopped, as before.
- **A step that isn't a hunt is followed by a stop check.** A Ctrl-C during `uv sync`, `docker build` or `docker cp`
  reaches that tool too, because it's in the same process group or console. The campaign then stops before starting
  another hunt, where it used to unwind from wherever the exception landed.
- **A deterministic regression test.** It forces a real `SIGINT` just after `Popen`'s wait takes its lock, and checks
  that the campaign's wait stops promptly and gets the hunt's exit code. A watchdog releases the lock if the wait
  hangs, so the test fails rather than hanging. It fails on today's code.
- **The end-to-end test's SIGABRT stack dump stays** as a backstop for any other cause.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `flake-hunt`: "The campaign reports every hunt together" gains a scenario: an interrupt that lands at any moment
  of the wait on a hunt still stops the campaign within its stop limit.

## Impact

- `scripts/flake_campaign.py`: signal handling in `campaign()`, `wait()` and the loop between hunts.
- `scripts/tests/workspace/test_flake_campaign.py`: the new regression test. The end-to-end interrupt test is
  unchanged.
- `scripts/flake_hunt.py` is unchanged. Its main thread waits on worker threads, not on `Popen`, and the failing
  run showed the hunt stopping and summarising correctly (design D3).
