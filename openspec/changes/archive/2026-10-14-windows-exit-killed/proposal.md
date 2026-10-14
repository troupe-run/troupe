# Proposal

Issue: troupe-run/troupe#86. The owner settled the issue's open question while this change was being proposed:
**`ending` records how the runner process actually ended**, and the host has to make that true. Related: #81, which
has a different cause and is not changed here.

## Why

`test_each_protocol_violation_crashes_the_run_naming_it[after result]` fails on Windows in 5 of the last 6 CI runs,
and the Windows `check` jobs are required, so it blocks every PR. The cause is a race between two things that happen
at almost the same time, and it isn't specific to Windows:

1. After the runner's `result`, the host sends `shutdown` (`host.py` `_supervise`). The scripted runner's `hang`
   step still answers messages, so it replies to `shutdown` and exits 0.
2. The host reads the late `log` line, finds the violation and calls `kill()`. `kill()` sets `killed = True` only if
   `child.returncode is None`.

If the runner's exit has been reaped before step 2, the host records `exited`, and that is true: the runner exited 0
by itself. Windows loses this race more often. `319eb40` did not cause it. It also failed once before that commit,
on #78.

The race also runs the other way, on every platform. asyncio only sets `returncode` once it has reaped the process.
So a runner that exited just before the grace-period kill can still read `None`, and the host records `killed` for a
process troupe never killed. If the runner sent an `ok` result, the run then ends `failed` with `run.unclean-exit`
when it should have `succeeded`. `ending` is part of the recorded run (`Run.Ended`), so either way the history says
something that didn't happen.

## What Changes

- **`ending` is `killed` only when troupe's kill ended the process.** The host no longer decides this from
  `returncode` before it kills. It decides from how the process actually ended: troupe sent a kill, *and* the exit
  status is the one that kill produces. A runner that exits by itself before the kill lands is `exited`, with its
  own exit code. This happens after a violation, after the grace period, or after a cancel.
- **The process seam tells the host whether its kill ended a child.** This is OS-specific, so it lives in
  `platform/processes.py` (design D1, D2). On Linux and macOS a kill ends the child with `SIGKILL`. On Windows,
  troupe now terminates the job with its own named exit code instead of `1`, so a kill can be told apart from a
  runner that exits 1. **BREAKING (Windows only, pre-alpha):** a killed run's recorded `exitCode` on Windows changes
  from `1` to that code. The schema already allows any integer.
- **The test says what it checks.** The ten violation cases where nothing told the runner to exit keep asserting
  `killed`. The `after result` case is its own test. Its name says the runner may answer the host's `shutdown` before
  the kill lands. It asserts the two endings that can happen and that each is consistent: `killed`, or `exited` with
  code 0.
- **Deterministic tests for both directions of the race** at the seam: a child troupe killed, a child that exited
  before a late kill, and a child that exited by itself with the kill's exit code. These don't depend on timing.
- **Docs:** `docs/runners.md` and `docs/platform.md` say what `ending` means and how each platform tells a kill
  apart. `Ending.KILLED`'s docstring stops claiming it only happens after the grace period.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `actor-runners`: adds the rule that a run's `ending` records how the runner ended, with scenarios for a violation
  kill, a runner that exits before the kill lands, and an `ok` result whose runner exits just as the grace period
  ends.
- `platform`: adds the rule that a child's end says whether troupe's kill ended it, on Linux, macOS and Windows.

## Impact

- Code: `packages/troupe/src/troupe/platform/processes.py` (the Windows termination code, and whether a kill ended
  the child), `packages/troupe/src/troupe/core/runners/host.py` (ending from the process's end, not from a
  `returncode` check), `packages/troupe/src/troupe/core/runners/outcome.py` (the `Ending` docstring).
- Tests: `test_run_host.py` (the violation test split, both directions of the race), `test_platform_processes.py`
  (the seam's kill attribution on all three platforms).
- Recorded data: no schema change. On Windows, newly recorded killed runs carry the new exit code. Existing records
  are left as they are: there are no theatres to migrate yet.
- Not changed: how or when the host kills, the grace periods, outcome derivation (`derive_outcome` already reads
  `ending`, so it now gets a true one), the scripted runner, and #81.
