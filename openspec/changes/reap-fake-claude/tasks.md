# Tasks

## 1. The ledger: each stand-in records itself and holds a lock while it runs

- [ ] 1.1 In `plugins/runner-claude-code/tests/fake_claude.py`, when `FAKE_CLAUDE_LEDGER` is set, take an exclusive
  lock on `<ledger>/<pid>.lock` first and hold it for the process's life, then write `<pid>.json` (pid, cwd, argv)
  whole. Add the reader's side: list entries, whether an entry's lock is still held, and stop a pid. Document
  `FAKE_CLAUDE_LEDGER` in the module docstring (D2). Verify with tests in `test_claude_code_fake.py`: a hanging
  stand-in's lock reads as held while it runs and as released once it's killed, on all three OSes in CI.
- [ ] 1.2 `install()` writes `FAKE_CLAUDE_LEDGER` into the shim when it's set in the installing process, and leaves it
  out when it isn't (D2). Verify with tests: with it set, a stand-in started with an environment that doesn't
  include it still registers; with it unset, the shim has no ledger line and no entry is written.
- [ ] 1.3 Test the pid-reuse case on the reader's side: a `.lock` entry nothing holds, whose pid now belongs to a live
  process the test started, reads as ended, and that process isn't signalled (spec: "A stand-in's pid is taken by
  another process"). Verify the test passes, and fails when the reader is changed to check `alive(pid)` instead.

## 2. The check: a test that leaves a stand-in running fails

- [ ] 2.1 Add `plugins/runner-claude-code/tests/stand_in_guard.py`: configure sets `FAKE_CLAUDE_LEDGER` to the
  ledger worked out from the pid, and unconfigure removes it. Setup and teardown wrappers check the entries added
  during each test, with `STAND_IN_END_SECONDS` named and explained. They stop survivors and fail the teardown
  naming each pid and working directory (D3). Load it from a new `plugins/runner-claude-code/tests/conftest.py`.
  Verify mypy --strict and ruff pass on it.
- [ ] 2.2 Test the check with a child pytest in `tmp_path` (`--confcutdir` set): a test that starts a hanging
  stand-in and ends without stopping it fails at teardown, naming the stand-in's pid and working directory, and
  afterwards the stand-in isn't running. A test whose stand-in exited passes. Verify both, on all three OSes in CI.
- [ ] 2.3 With the harness still unchanged, run `test_a_second_run_start_is_refused` on macOS and confirm that the
  check fails it, naming the stand-in under that test's temp directory, and that no `fake_claude.py` process is left
  afterwards (`pgrep -f fake_claude.py` shows nothing new). This is D4's evidence. Record the output in the commit
  message.
- [ ] 2.4 Add `packages/troupe/tests/conftest.py`, which loads `stand_in_guard.py` by path and binds its hooks for
  core's tests (D3). Verify that `uv run scripts/check_paths_reach.py` shows no suite's reach changed, and that the
  check-paths reach test passes. Run core's stand-in tests (`test_claude_code_host.py`, `test_perform_claude_code.py`,
  `test_runner_conformance.py`, `test_perform.py`, `test_user_docs_pages.py`) and confirm they pass with the check on.

## 3. The harness: end the runner as troupe does

- [ ] 3.1 In `plugins/runner-claude-code/tests/claude_harness.py`, start the runner with `start_new_session=True` on
  POSIX, and have `Session.kill()` send `SIGKILL` to its group, ignoring `ProcessLookupError`, before waiting (D1).
  On Windows it still kills the runner's process. Update the class docstring to say that it ends the runner as
  troupe's `kill_tree` does. Verify that `test_a_second_run_start_is_refused` now passes with the check on, and that
  `pgrep -f fake_claude.py` shows nothing new after the plugin's whole suite.
- [ ] 3.2 Add a test for the spec's "A test ends while the stand-in hangs" scenario: start a run whose stand-in hangs,
  send a second `run/start`, call `Session.kill()`, and assert that neither the runner's pid nor the stand-in's
  (from its record) is running. Verify it passes, and fails when `kill()` goes back to killing the runner's pid alone.

## 4. Integration

- [ ] 4.1 Run `uv run scripts/check.py` and confirm it passes. Then run the plugin's and core's suites under xdist
  (as `check.py` does) and confirm that no `fake_claude.py` process is left after they finish.
- [ ] 4.2 Confirm CI passes on Linux, macOS and Windows, with the check on, once the PR is marked ready. Record the
  run id here, as in earlier changes.

## Workflow follow-up

- Open the draft PR with `Closes #276`, act on Claude's review of the last push, and mark it ready once it's clean.
- Archive the change on the branch before the owner merges.
- After the merge, comment on #276 with the PR and the archived change, and check that its card says Done.
