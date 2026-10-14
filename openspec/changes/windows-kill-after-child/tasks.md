# Tasks

## 1. Measure the unchanged test on Windows CI (design D4)

- [ ] 1.1 Commit a temporary `@pytest.mark.parametrize("attempt", range(50))` on the unchanged race test, with a
  message saying it's a measurement for #90 and will be reverted. Open the PR as a draft (`Closes #90`) and record, for
  each `windows-latest` job (Python 3.12 and 3.13), the run id and how many of the 50 runs failed, with the failing
  tuples. Verify by the recorded counts, whatever they are. No failure is recorded as "not reproduced on CI", not
  skipped

## 2. The child exits on the test's signal (design D1)

- [ ] 2.1 Change the race test's child to print `up`, then poll for the file named by its argument for at most 30 s,
  exiting 0 when it appears and 3 when it doesn't. Have the test await `up` and create the file (under `tmp_path`)
  with no await between that and the kill. Verify the test passes locally on macOS, and that `time.sleep(0.5)` no
  longer appears in it (`grep`)

## 3. The exit is proven before the kill (design D2, D3)

- [ ] 3.1 Replace `_block_until_exited` with `_wait_for_exit`, bounded by a named `EXIT_BOUND_SECONDS = 30`: a
  `ctypes` handle wait and `GetExitCodeProcess` on Windows (the handle opened before the file is created and closed
  in `finally`), `waitid` with `WNOWAIT | WNOHANG` polled on Linux, and `os.kill(pid, 0)` polled on macOS. Verify
  `uv run pytest packages/troupe/tests/test_platform_processes.py` passes locally, and that the module no longer
  calls `processes.is_running` from this test or its helper (`grep`)
- [ ] 3.2 Add the precondition checks in D3's order, each failing with a message starting `precondition not
  reached:`, and assert `(exit_code, ended_by_kill) == (0, False)` only after them. Verify each message fires on its
  own, with temporary edits reverted and shown reverted with `git diff --stat`: not creating the file gives "exited
  with 3"; an `await asyncio.sleep(1)` after creating the file gives "asyncio saw the exit"; a bound of 0.01 s with
  the child sleeping first gives "did not exit within"
- [ ] 3.3 Verify the test still catches #87's regression: with `ended_by_kill` temporarily returning `self._kill_sent`
  alone, the test fails on the kill assertion, not on a precondition. Revert and show it reverted with
  `git diff --stat`
- [ ] 3.4 Run `uv run scripts/check.py`. Verify every gate passes (mypy `--strict` included, on the `ctypes` code
  behind `if WINDOWS`)

## 4. Measure the changed test on Windows CI, then remove the repetition (design D4)

- [ ] 4.1 Re-apply the 50-run parametrize on the changed test, push, and record each `windows-latest` job's run id and
  result. Verify all 100 Windows runs pass, and Linux and macOS pass. A precondition failure doesn't tick this task:
  record its message and run id and take it to the owner
- [ ] 4.2 Revert the repetition in its own commit, saying why. Verify `range(50)` no longer appears in the module
  (`grep`), and that all CI jobs pass on Linux, macOS and Windows for the PR's final commit

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging.
- After the merge, comment on #90 with the PR and the archived change, and close it.
