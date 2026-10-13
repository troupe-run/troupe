# Tasks

## 1. The seam says whether its kill ended a child

- [x] 1.1 Write the three seam tests from design D3 in `test_platform_processes.py` first: a killed running child
  (`ended_by_kill` true); a child that exited 0 and was then killed before `wait()` (exit code 0, `ended_by_kill`
  false); a child that ends itself with the kill's status and was never killed (`ended_by_kill` false). Verify they
  fail on main for the missing API only (an `AttributeError`, not a wrong value)
- [x] 1.2 In `platform/processes.py`, add `KILLED_EXIT_CODE = 0x74726B6C` and pass it to `TerminateJobObject` in
  `_kill_job` (design D2). `ChildProcess.kill_tree()` records that a kill was sent, and add
  `ChildProcess.ended_by_kill(exit_code: int) -> bool` (Linux and macOS: `-SIGKILL`; Windows: `KILLED_EXIT_CODE`),
  with docstrings saying what each one means. Verify the 1.1 tests and the existing `test_platform_processes.py`
  pass locally
- [x] 1.3 Document it in `docs/platform.md`: the Stopping bullet says how each platform tells a kill apart, and names
  `KILLED_EXIT_CODE` and its value. Verify by reading the rendered section against design D2

## 2. The host records how the runner ended

- [ ] 2.1 Before changing the host, confirm the checks that must pass on main and after it. A runner that ignores
  `run/cancel` or `shutdown` past the grace period still ends `killed`: the existing
  `test_a_runner_ignoring_cancel_is_killed_with_the_process_it_started` and
  `test_a_runner_that_ignores_shutdown_after_its_result_is_killed_and_fails_as_uncertain`. A clean `ok` run still ends
  `exited` 0 `succeeded`: add an assertion on `ending` and `exit_code` if no host test checks it yet. Verify they pass
  on main
- [ ] 2.2 In `core/runners/host.py`, remove `_Run.killed` and set `ending` from `child.ended_by_kill(exit_code)`
  (design D1). Keep `kill()`'s `returncode is None` guard with a comment that it protects against pid reuse and no
  longer decides `ending`. Update `Ending.KILLED`'s docstring in `outcome.py` to say troupe's kill ended the
  process, whichever path sent it. Verify the 2.1 tests still pass
- [ ] 2.3 Split the violation test (design D3): remove `after result` from
  `test_each_protocol_violation_crashes_the_run_naming_it`, which keeps `ending is Ending.KILLED` for the ten
  remaining cases. Add
  `test_a_late_event_after_the_result_crashes_the_run_whether_the_runner_answers_shutdown_first`, asserting
  `crashed`, `runner.protocol`, "after its result" and "line", and
  `(ending, exit_code) == (KILLED, <kill status>)` or `(EXITED, 0)`. Verify both tests pass, and run the new one
  100 times locally (`for i in $(seq 100); do uv run pytest -q "<node id>" || break; done`), recording how often
  each ending occurred
- [ ] 2.4 Document `ending` in `docs/runners.md` where the outcome lists what it records: `killed` means troupe's kill
  ended the runner, and a runner that exits by itself first is `exited` with its own code. Verify the paragraph
  matches the `actor-runners` requirement "A run's ending records how the runner ended"

## 3. Whole change

- [ ] 3.1 Search `packages/` and `plugins/` for other readers of `returncode` that decide something about a kill
  (`grep -rn "returncode" packages plugins`) and confirm none does, or fix it under D1. Verify by the search output,
  listed in the PR
- [ ] 3.2 Run `uv run scripts/check.py`. Verify it passes (ruff, mypy --strict, the full test suite)
- [ ] 3.3 Push and verify every CI job passes on Linux, macOS and Windows. Then re-run the Windows jobs twice more
  (Windows failed 5 of 6 runs before this change) and verify all three attempts pass

## Workflow follow-up

- Open the PR with `Closes #86`. Include the 2.3 tally of endings, the 3.1 search and the three Windows attempts.
- Run `/opsx:archive` on the branch before merging.
- After the merge, comment on #86 with the PR and the archived change.
