# Proposal

Issue: #187.

## Why

Three times (#186 run 40671505530, #191 run 40862984108, #203 run 41024790045) the `check (windows-latest, Python
3.12)` leg reached 97–98% of the suite, printed nothing more, and was stopped by the job's 20-minute timeout. Rerunning
passed each time, and the other eleven legs passed. The summary always reads two short of the tests collected (for
example 2977 passed and 22 skipped of 3001). An xdist worker always holds the test after the one it is running, so
this is one stuck test, not two. The log can't say which: the suite runs under xdist with `-q`, so it prints dots, and
nothing dumps a stuck test's stack. A hang that names no test can't be fixed with evidence, and while it remains, any
pull request's Windows 3.12 leg can fail for nothing it changed.

The one clue is the warning printed as the job stopped: an asyncio subprocess transport, collected unclosed, whose
stdout pipe was already closed. That points at a child started through `troupe.platform.processes.start`. Reading the
seam shows a defect that can hang exactly that way:

- On Windows, `start` (and `run_to_completion`) creates the child **running** and only then assigns it to its kill-on-close
  job. Anything the child starts in that gap is outside the job. `contributing/platform.md` lists this as a known
  limitation, on the grounds that "runners start nothing before they read their first message". But a virtual
  environment's `python.exe` is a launcher that starts the real interpreter as its own child straight away, and the
  tests start their stand-in runners with it.
- `kill_tree` then terminates the job, which holds the launcher but not the interpreter that got out. The interpreter
  keeps the child's stdout pipe open.
- asyncio's `Process.wait()` doesn't return until every pipe has closed, so the test waits forever.

The platform spec already requires that killing a child kills every grandchild, so this gap breaks the spec on
Windows. `scripts/flake_hunt.py` closed the same gap for its own rounds by starting them suspended.

## What Changes

- **A stuck test names itself.** The tests gate dumps every thread's stack, including the test's own frame, once a
  single test has run past a named stall limit (5 minutes). The test keeps running, so the dump only adds to the log
  and changes no outcome. This works in xdist workers, so CI's log names a stuck test well before the job's 20-minute
  timeout. The limit is set in one place, the pytest configuration, which the flake hunt also reads unless `--stall`
  is given.
- **The hang is identified before anything is fixed.** The stack dump is pushed on its own, and the Windows 3.12 leg
  is rerun until a dump names the stuck test, up to a limit set in advance (design D3). Only then does the fix go
  out, so a hang that stops can be told apart from one that wasn't caught.
- **Nothing a Windows child starts can get out of its job.** `start` and `run_to_completion` start the child
  suspended, assign it to the job, and only then let it run, as the flake hunt does. If assigning or resuming fails,
  the child is killed and the error is raised. The gap is first shown with a test that widens it on purpose, so the
  test fails on the current code and passes with the fix. `contributing/platform.md` drops the limitation.
- **The hung test bounds itself.** Whichever test the dump names gets its own named limit on the wait that hung
  (memory/no-per-test-timeout: there is no per-test timeout), so a regression fails it, naming the limit, instead of
  hanging. If the dump points to a cause other than the job gap, that cause is fixed too. The design is updated
  before any code depends on it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `platform`: "Killing a child kills its whole process tree" gains a scenario for a grandchild the child starts
  straight away, before troupe could act, on every platform and through both ways of starting a child.
- `quality-check`: a new requirement that a test running past the stall limit has its stack written to the check's
  output, naming the test, in parallel and in CI on every platform, without changing the result.

## Impact

- `packages/troupe/src/troupe/platform/processes.py`: suspended start, job assignment, then resume on Windows, for
  `start` and `run_to_completion`. The module docstring changes to match.
- `packages/troupe/tests/test_platform_processes.py`: the deterministic grandchild-escape test.
- `pyproject.toml`: `faulthandler_timeout` in `[tool.pytest.ini_options]`.
- `scripts/flake_hunt.py`: `--stall` defaults to the configuration's limit instead of repeating it.
- `scripts/tests/`: a test that a stalled test's stack reaches the output of a parallel run.
- The test the dump names, whatever it is, and anything its cause needs.
- `contributing/platform.md`: the Windows job-assignment limitation is removed, and the process table describes the
  suspended start.
- Process: the PR is marked ready before Claude's review of the dump push is clean, so that its legs run (owner's
  choice, 2026-10-31). Then the Windows 3.12 job is rerun with `gh run rerun --job`.
