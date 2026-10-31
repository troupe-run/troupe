# Tasks

## 1. A stuck test names itself (pushed alone: design D1, D2)

- [x] 1.1 In `scripts/tests/test_check_parallel.py`, add a test that a stalled test's stack reaches a parallel run's
  output. Use a pytester root with `faulthandler_timeout = 1`, a test that sleeps 3 s and a quick test, run with
  `gate_command()`. Assert that the output holds `Timeout (` and a frame naming the sleeping test's function, and that
  the run passes. Add a second test asserting that a quick-only run holds no `Timeout (`. Verify: `uv run pytest
  scripts/tests/test_check_parallel.py -k stall` passes. Then set the sleep below the limit and check the first test
  fails (then revert). Outcome on macOS: 2 passed (2.7 s and 2.4 s). With the sleep at 0.2 s the first test failed
  on `'Timeout (0:00:01)!' in ...`; reverted. The sleep is the limit plus 1.5 s, not 3 s
- [x] 1.2 In `pyproject.toml`'s `[tool.pytest.ini_options]`, set `faulthandler_timeout = 300` with a comment naming
  #187 and the reasoning in D1. Add a test that reads `pyproject.toml` and asserts the limit is set, above 120 s and at
  most 600 s (named constants for the slowest-test margin and the job's timeout less the suite). Verify: the test
  passes. Then remove the setting and check the test fails (then restore). Outcome: the file's 10 tests passed. With
  the setting removed, the test failed with "pyproject.toml sets no stall limit"; restored
- [x] 1.3 In `scripts/flake_hunt.py`, make `--stall` default to none and pass `-o faulthandler_timeout` only when it's
  given. Remove `STALL_SECONDS`, and update `contributing/flake-hunt.md`'s options table to say the default comes from
  `pyproject.toml`. Add a test that `round_command` has no `faulthandler_timeout` override without `--stall`, and has
  `--stall 60`'s value with it. Verify: `uv run pytest scripts/tests/test_flake_hunt.py` passes, including the
  existing stuck-test test. Outcome: 29 passed, 2 skipped (Windows-only); ruff and mypy clean
- [x] 1.4 Run `uv run scripts/check.py`, and verify every gate passes, recording the counts. Commit 1.1–1.3 in small
  commits, push, open the PR as a draft with `Closes #187`, then mark it ready (`gh pr ready`) so its legs run (D3, the
  owner's choice). Verify: every leg of that run passes, and the Windows legs' logs show 1.1's tests passed there,
  so the dump reaches the log on Windows. Outcome: check passed locally (3052 passed, 14 skipped). The guard's
  pre-commit check refused separate commits while other tracked files had unstaged changes, so 1.1–1.3 went in as one
  commit (bff6b3b). PR #211, run 41194587297: 11 legs passed, Windows 3.13–3.15 included, so 1.1's tests passed on
  Windows. Windows 3.12 hung and was stopped at its timeout, but its log holds the dump (2.1), which is the proof
  that the dump reaches the log on Windows

## 2. Catch the hang (design D3)

- [x] 2.1 Catch the hang and name its test. Outcome: the hunt wasn't needed. The stage 1 run's own Windows 3.12 leg
  (run 41194587297, job 124518135781) stalled at 96%. At 11:01:35 the dump printed `Timeout (0:05:00)!`, and the test
  thread's stack named `test_platform_processes.py`, line 396, in
  `test_a_line_over_the_maximum_is_an_error_naming_the_maximum`, then line 386 in `_first_line` (`asyncio.run`), over
  the proactor's `_poll`. The job was stopped at 11:14:04 with 3040 passed, 22 skipped of 3064, followed by the same
  `BaseSubprocessTransport` / closed-pipe warning. The hunt workflow (D3) was written but never pushed. It is kept
  for 5.2
- [x] 2.2 Find the cause and update the design before any code depends on it. Outcome: not the job gap. A refused
  over-long line can leave the child's stdout stream paused, so `wait()` never sees end-of-file. Reproduced
  deterministically on macOS. With a child that keeps running after writing 2 MiB and a line feed, reading after the
  line has arrived left `wait()` still waiting 5 s after `kill_tree()`, and reading at once let it return. The run
  host's `_finish_process` takes the same path with an unbounded `wait()`. Design D3's outcome, D5 and D6, and a new
  platform requirement, were recorded before the fix was written
- [ ] 2.3 Comment on #187 with the run, the test, its stack and the cause (design D6). Verify: the comment is posted

## 3. No Windows child gets out of its job (design D4)

- [ ] 3.1 Add the `_before_job_assignment` hook (a no-op by default) and the escape test for `start` in
  `packages/troupe/tests/test_platform_processes.py`, as D4 describes (`ESCAPE_WINDOW`, `WAIT_LIMIT`). Add the
  matching test for `run_to_completion`'s timeout path. Verify: both pass on macOS. Their Windows failure on the
  unfixed seam is shown in 3.3, since there's no Windows machine locally
- [ ] 3.2 Start Windows children suspended in `start` and `run_to_completion`, and have `_new_job_for` assign and
  resume them (`NtResumeProcess`). On failure, close the job and raise an `OSError` naming the step and the pid; the
  callers kill the child and wait for it. Update the module docstring, `contributing/platform.md`'s process table, and
  remove its "Windows job assignment" limitation. Verify: `uv run pytest packages/troupe/tests/test_platform_processes.py`
  passes, `uv run mypy` is clean, and `uv run mypy --platform win32` on the module is clean
- [ ] 3.3 Show the escape test fails on Windows without the fix. Push 3.1's tests (with the hook) first, without
  3.2, and check that the Windows legs fail them at `WAIT_LIMIT` (`start`) and on the surviving grandchild
  (`run_to_completion`). Then push 3.2 and check every leg passes. Verify: both runs' ids and the failing assertions
  are recorded here

## 4. Waiting ends once the child has exited (design D5, D6)

- [ ] 4.1 Add the seam test from D6: a child writes 2 MiB and a line feed against a 1 MiB limit, flushes and sleeps.
  The test waits (bounded) for the stdout pipe to pause, reads (`LineTooLongError`), kills the tree, and asserts that
  `wait()` returns within `WAIT_LIMIT` with the kill's status, and that the rest of stdout can still be read whole
  afterwards. Verify: it fails at `WAIT_LIMIT` on the unfixed seam (run before 4.2)
- [ ] 4.2 In `ChildProcess.wait()`, once the child's exit code is known, resume reading any of its paused output
  pipes (D6). Update the docstring. Verify: 4.1's test passes, the whole of `test_platform_processes.py` and the run
  host's tests pass, and mypy is clean
- [ ] 4.3 In `_first_line`, the helper of the test that hung, bound `await child.wait()` with `WAIT_LIMIT` and a
  failure message naming the limit and what it waited for (D5). Verify: the line tests pass. With 4.2's fix removed
  and the stream forced to pause (a sleep before the read), the over-long test fails at the limit with that message
  instead of hanging (then restore)

## 5. Verify

- [ ] 5.1 Run `uv run scripts/check.py`, and verify every gate passes, recording the counts
- [ ] 5.2 Push the fixed head together with the hunt workflow (D3, set aside since 2.1), and run one batch (40 copies
  of the Windows 3.12 check). Verify: no copy hangs, and no log holds `Timeout (`. Record the counts here. This is the issue's
  "a flake hunt on Windows passes with no hung rounds", done on the leg that hung
- [ ] 5.3 Delete `.github/workflows/hang-hunt-187.yml` in a push of its own. Verify: `git ls-files .github/workflows`
  doesn't list it, `git diff main --stat -- .github` is empty, and that push starts no hunt run

## Workflow follow-up

- Act on Claude's review of the last push: fix or answer each finding, resolve only nits, and raise decisions with the
  owner. Then archive the change on the branch (`/opsx:archive`), which syncs the `platform` and `quality-check`
  deltas.
- A new requirement in `quality-check` doesn't change its Purpose, so `oob/troupe-spec-purposes.json` in
  infrastructure needs no change. Check infrastructure's drift job anyway.
- Ask the owner to merge once every check passes and every conversation is resolved.
- After the merge, comment on #187 with the PR, the archived change and the test that hung. Then check the issue is
  closed and its roadmap card says Done.
