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
- [ ] 1.4 Run `uv run scripts/check.py`, and verify every gate passes, recording the counts. Commit 1.1–1.3 in small
  commits, push, open the PR as a draft with `Closes #187`, then mark it ready (`gh pr ready`) so its legs run (D3, the
  owner's choice). Verify: every leg of that run passes, and the Windows legs' logs show 1.1's tests passed there,
  so the dump reaches the log on Windows

## 2. Catch the hang (design D3)

- [ ] 2.1 Rerun the Windows 3.12 job on the 1.4 head with `gh run rerun <run-id> --job <job-id>`, one at a time, until
  a dump names the stuck test or D3's stopping rule is reached. Record each attempt here (attempt, outcome, and for a
  hang the test and the first frames of its stack). Verify: the record lists every attempt. On a hang, the log holds
  `Timeout (` followed by a frame in a test file
- [ ] 2.2 If a test was named, comment on #187 with the run, the test and its stack, and record here whether the stack
  shows a wait on a child (`Process.wait`/`_wait` under `base_subprocess`). If the stack points to a cause other than
  the job gap, update design.md with `/opsx:update` before writing any code for it. If nothing hung within the rule,
  stop and ask the owner (D3). Verify: the comment is posted, or the owner's answer is recorded here

## 3. No Windows child gets out of its job (design D4)

- [ ] 3.1 Add the `_before_job_assignment` hook (a no-op by default) and the escape test for `start` in
  `packages/troupe/tests/test_platform_processes.py`, as D4 describes (`ESCAPE_WINDOW`, `WAIT_LIMIT`). Add the
  matching test for `run_to_completion`'s timeout path. Verify: both pass on macOS. Their Windows failure on the
  unfixed seam is shown in 3.3, since there's no Windows machine locally
- [ ] 3.2 Start Windows children suspended in `start` and `run_to_completion`, then assign and resume with
  `_assign_and_resume` (`NtResumeProcess`). On failure, terminate the child, wait for it, close the job and raise an
  `OSError` naming the step and the pid. Update the module docstring, `contributing/platform.md`'s process table, and
  remove its "Windows job assignment" limitation. Verify: `uv run pytest packages/troupe/tests/test_platform_processes.py`
  passes, and `uv run mypy` is clean
- [ ] 3.3 Show the escape test fails on Windows without the fix. Push 3.1's tests first, alone, and check that the
  Windows legs fail them at `WAIT_LIMIT` (`start`) and on the surviving grandchild (`run_to_completion`). Then push
  3.2 and check every leg passes. Verify: both runs' ids and the failing assertions are recorded here

## 4. The hung test bounds itself (design D5)

- [ ] 4.1 In the test 2.1 named, wrap the wait that hung in `asyncio.wait_for` with a named module-level limit and a
  failure message naming the limit and what it waited for. Verify: the test passes. Then make it block (for example,
  skip the kill it relies on) and check it fails at the limit with that message instead of hanging (then revert).
  If 2.1 named no test, record "not applicable" with the owner's decision from 2.2
- [ ] 4.2 If 2.2 found a different cause, fix it as the updated design says, with a test that fails before the fix.
  Verify: as the updated design states. Otherwise record "not applicable: the stack showed the job gap"

## 5. Verify

- [ ] 5.1 Run `uv run scripts/check.py`, and verify every gate passes, recording the counts
- [ ] 5.2 Run the Windows 3.12 job on the final head as many times as D3's rule, with `gh run rerun --job`. Verify: no
  attempt hangs, and none of the logs holds `Timeout (`. Record the attempts here. This is the issue's "a flake hunt
  on Windows passes with no hung rounds", done on the leg that hung

## Workflow follow-up

- Act on Claude's review of the last push: fix or answer each finding, resolve only nits, and raise decisions with the
  owner. Then archive the change on the branch (`/opsx:archive`), which syncs the `platform` and `quality-check`
  deltas.
- A new requirement in `quality-check` doesn't change its Purpose, so `oob/troupe-spec-purposes.json` in
  infrastructure needs no change. Check infrastructure's drift job anyway.
- Ask the owner to merge once every check passes and every conversation is resolved.
- After the merge, comment on #187 with the PR, the archived change and the test that hung. Then check the issue is
  closed and its roadmap card says Done.
