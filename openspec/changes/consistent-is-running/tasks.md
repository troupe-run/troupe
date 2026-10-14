# Tasks

## 1. Pin what must stay the same, on main's code

- [x] 1.1 Confirm the issue's reproduction where it can run locally: on macOS, `is_running(1)` as a non-root user
  returns `True`. Record the result (and that the Windows row, `is_running(4)` → `False`, is confirmed on CI by
  1.3) for the PR
- [x] 1.2 Add the "must stay the same" tests from design Goals to `test_platform_processes.py` under a heading for
  the new requirement: a live child reads running; a waited-for child reads ended; POSIX pid 1 reads running when
  not root (skipped as root, saying why); a POSIX unreaped child reads running, named as the documented limit.
  Verify they pass against main's `is_running`, before any change to it
- [ ] 1.3 Add the Windows tests that fail on main: a child that denies everyone access to its own process (an
  empty DACL, which refuses an elevated administrator too) reads running, and a child that exited with code 259
  while its `Popen` still holds it reads ended. Mark both `xfail(strict=True)` with the reason "#92: fixed by
  group 3". Add the System process (pid 4) reads running as a non-strict xfail, because CI's administrator may be
  able to open it and then main already answers right. Verify on Windows CI that the strict two xfail, and record
  what main returned for pid 4 for the PR. (Applying showed the empty-DACL xfail came from its setup: CI could still
  open the process. Its reproduction is now the helper in 3.2, which proves the refusal happens; main returns
  `False` for any failed open, so its answer there follows from its code.)

## 2. The decision tables (design D2, D5, D6)

- [x] 2.1 Add `ProcessStateUnknownError(pid, code, text)` to `troupe.platform.errors` (design D6). Verify a test
  that its message names the pid, the text and the code
- [x] 2.2 Add the module-level `_posix_outcome` and `_windows_outcome` to `processes.py`, and the pid check
  (design D5). Verify parametrised tests for every row of both tables pass on every platform, and a Hypothesis
  property that any errno or Windows error outside the known ones raises `ProcessStateUnknownError` with that pid
  and code
- [x] 2.3 Verify tests that `0`, `-1`, `2**31` and `True` raise `ValueError` naming the value, and that no OS call is made
  (by monkeypatching `os.kill` on POSIX and the open call on Windows to fail the test if reached)

## 3. Wire each platform's OS calls to its table (design D3)

- [x] 3.1 POSIX `is_running`: check the pid, call `os.kill(pid, 0)`, pass the result to `_posix_outcome`. Verify
  group 1's tests still pass, and a test that monkeypatches `os.kill` to raise `OSError(EINVAL)` gets
  `ProcessStateUnknownError` naming the pid and `EINVAL`
- [ ] 3.2 Windows `is_running`: bind `WaitForSingleObject`, open with `PROCESS_QUERY_LIMITED_INFORMATION |
  SYNCHRONIZE`, take `ctypes.get_last_error()` at each failing call, close the handle in every path, pass the
  results to `_windows_outcome`. Remove the `xfail`s from 1.3. Verify on Windows CI that all three tests pass, and
  record which branch pid 4 took (access denied or wait) for the PR
- [ ] 3.3 Add the cross-platform test that a child exiting with code 259 reads ended (waited for on POSIX, held on
  Windows). Verify it passes on all three CI platforms
- [x] 3.4 Update both `is_running` docstrings and the module docstring's platform list to the one meaning, the
  three outcomes and the POSIX zombie limit. Verify they match the spec requirement's wording

## 4. Documentation

- [x] 4.1 `docs/platform.md`: add a row to the platform table for "Whether a process has ended" (POSIX `kill(pid,
  0)`; Windows the signalled handle), a bullet under Child processes for the three outcomes and the pid check, and
  the unreaped-zombie entry under Known limitations with why no caller is affected (design D4). Verify each claim
  against the code and tests from groups 2 and 3

## 5. Integration

- [ ] 5.1 Verify the existing callers pass unchanged on all three platforms: the kill-tree tests in
  `test_platform_processes.py`, `test_a_runner_ignoring_cancel_is_killed_with_the_process_it_started` in
  `test_run_host.py`, and `test_a_hung_git_times_out_and_its_whole_tree_is_stopped` in `test_git_adapter.py`
- [ ] 5.2 Run `uv run scripts/check.py` (ruff, format, mypy --strict, import-linter, the full suite). Verify it
  passes locally and on CI on Linux, macOS and Windows

## Workflow follow-up

- Open the PR with `Closes #92`, recording 1.1's and 1.3's reproductions and 3.2's pid 4 branch. If #90's branch
  (`windows-kill-after-child`) lands first, rebase onto it.
- Archive the change on the branch before merging; after the merge, comment on #92 with the PR and the archived
  change.
