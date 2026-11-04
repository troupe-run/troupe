# Design

## Context

See proposal.md, "Why". Here's what the fix has to work with:

- troupe's platform starts every child with `start_new_session=True` on POSIX, or in a job of its own on Windows.
  `ChildProcess.kill_tree()` then kills the group with `os.killpg(pid, SIGKILL)`, or terminates the job
  (`packages/troupe/src/troupe/platform/processes.py`). The runner keeps Claude Code in its own process group on
  POSIX, so troupe's kill reaches it. On Windows the runner gives Claude Code a job nested in its own, created with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (`plugins/runner-claude-code/src/troupe_runner_claude_code/processes.py`).
- The plugin's harness (`tests/claude_harness.py`, `Session`) started the runner with a plain `Popen`, so it stayed in
  pytest's process group, and `Session.kill()` killed the runner's pid alone. The `sessions` fixture calls `kill()` on
  every session at teardown.
- Every runner test gives the stand-in a `FAKE_CLAUDE_RECORD` path, and the stand-in writes its pid there first, before
  it reads standard input.

## Goals / Non-Goals

**Goals:**

- The harness ends a runner as troupe does, so a test that ends mid-run leaves nothing behind.
- A runner test that leaves its stand-in running fails, so the leak can't come back unnoticed.

**Non-Goals:**

- Changing the runner or core. Their teardown is already right.
- Checking stand-ins started outside `Session`. In the plugin those are the stand-in's own tests, which wait for the
  processes they start. Core's tests run the runner through troupe's own `kill_tree`, which the platform spec's tests
  already cover.
- Stopping a leaked stand-in automatically. The check fails the test. Once the harness is right, nothing leaks, so a
  failure means the harness is broken again, and that is what needs fixing.
- The scripted runner's harness. It has the same `kill()`, but the scripted runner starts no process.

## Decisions

### D1. The harness starts and kills the runner as troupe's platform does

On POSIX, `Session` starts the runner with `start_new_session=True`, and `kill()` sends `SIGKILL` to the group
(`os.killpg`), ignoring `ProcessLookupError`, before it waits for the runner. This is what `kill_tree` does. It runs
even when the runner has already exited, because the group outlives its leader while any process in it runs.

On Windows the harness keeps killing the runner's process. When the runner ends, its handle to Claude Code's job
closes, and `KILL_ON_JOB_CLOSE` ends the stand-in. troupe's own job reaches the same result. The check (D2) runs on
Windows CI too, so if the job doesn't cover it, CI says so.

**Alternative: stop the stand-in in the test** (cancel the run before the test ends). That fixes one test, not the
cause. The issue asks for the teardown to work the way a real one does.

### D2. The `sessions` fixture checks each session's stand-in after killing it

At teardown the fixture kills each session, then asks it for its stand-in's pid from the record. If that pid is still
running `STAND_IN_EXIT_SECONDS` (5.0) later, the test fails, naming the pid and the workspace. The check sits where
the leak came from, and each test is judged on its own stand-in.

The check can only see a stand-in that has written its pid. A test that ends before then, as
`test_a_second_run_start_is_refused` did, has nothing to check. So that test waits for the record before it ends, as
the new kill test does. On the old harness the check then fails that test itself, naming its stand-in.

A pid the OS reuses during the wait could at worst make the check fail a test that's fine. It never signals anything,
so it can't stop an unrelated process.

### D3. A process ledger and a check for every suite, tried and removed (owner, 2026-11-04)

The first build of this change gave each stand-in a lock file in a per-process ledger, and loaded a pytest check for
every test in the plugin's and core's suites. The check stopped leaked stand-ins, using the lock to be sure a pid was
still the stand-in, and charged a late-starting stand-in to the next test. It worked. But it was about 650 lines of
OS-specific locking, conftests, a mypy exclusion, a ruff setting and child-pytest tests, plus timing races of its own,
all to cover cases that only arise if the harness bug comes back. The owner's view was that the cure was worse than
the cause. It's in the branch's history.

## Risks / Trade-offs

- [A later test that ends before its stand-in records its pid isn't checked] → D2's wait in the test is the pattern.
  Such a test ends mid-run, so it's one like `test_a_second_run_start_is_refused`, and the kill test is there as the
  example.
- [Windows relies on the runner's own job, not one the harness makes] → the check runs on Windows CI, so a stand-in
  that outlives its runner there fails a test.
