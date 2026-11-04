# Tasks

## 1. The harness: end the runner as troupe does

- [x] 1.1 In `plugins/runner-claude-code/tests/claude_harness.py`, start the runner with `start_new_session=True` on
  POSIX, and have `Session.kill()` send `SIGKILL` to its group, ignoring `ProcessLookupError`, before waiting (D1).
  On Windows it still kills the runner's process. Verify that `test_a_second_run_start_is_refused` leaves no
  `fake_claude.py` process from this worktree.
- [x] 1.2 Add a test for the spec's "A test ends while the stand-in hangs" scenario: start a run whose stand-in hangs,
  send a second `run/start`, call `Session.kill()`, and assert that neither the runner's pid nor the stand-in's (from
  its record) is running. Verify it passes, and fails when `kill()` goes back to killing the runner's pid alone.

## 2. The check: a runner test that leaves its stand-in running fails

- [x] 2.1 Add `Session.stand_in_left_running()`, which reads the stand-in's pid from its record and returns it if it
  is still running after `STAND_IN_EXIT_SECONDS`. Have the `sessions` fixture call it after killing each session and
  fail the test naming the pid and workspace. Make `test_a_second_run_start_is_refused` wait for its stand-in's record
  (D2). Verify that the runner tests pass, and that with `kill()` back to killing the runner's pid alone,
  `test_a_second_run_start_is_refused` itself fails at teardown, naming its stand-in. (Done: macOS, stand-in 57046,
  and the kill test's 57090.)
- [x] 2.2 Remove the first build's ledger and check (D3): `fake_claude.py`, `test_claude_code_fake.py`,
  `claude_stand_in.py` and `pyproject.toml` back as they were, and `stand_in_guard.py`, both conftests and
  `test_claude_code_stand_in_guard.py` deleted. Verify that the change's diff from its base touches only
  `claude_harness.py` and `test_claude_code_runner.py`, outside `openspec/`.

- [x] 2.3 From the review: move the check into `stand_in_left_running(record, seconds)`, make a record that names no
  pid an error naming it, note the zombie assumption, and test the function directly (a live process, an exited one,
  a missing record, five malformed ones). Verify the tests pass, and that 6 of them fail when the function always
  returns None.

## 3. Integration

- [x] 3.1 Run `uv run scripts/check.py` (through the commit) and confirm it passes, and that no `fake_claude.py` from
  this worktree is left after it.
- [x] 3.2 Confirm CI passes on Linux, macOS and Windows once the PR is marked ready. Record the run id here. (Linux,
  macOS and Windows, Python 3.12 to 3.15: CI run 41822899177 on 851950e)

## Workflow follow-up

- Act on Claude's review of the last push, and mark the PR ready once it's clean.
- Archive the change on the branch before the owner merges.
- After the merge, comment on #276 with the PR and the archived change, and check that its card says Done.
