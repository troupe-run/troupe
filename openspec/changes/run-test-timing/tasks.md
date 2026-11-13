# Tasks

## 1. Worktree events found by topic (#402, design D1, D2)

- [ ] 1.1 Write the threshold-0 pin first (D2): the #402 test's body with `WORKSPACE_ANNOUNCE_AFTER_SECONDS` at 0,
  asserting a `workspace.waiting` was recorded before `Run.WorktreeMade`. Verify: it fails on the current test body
  with `KeyError: 'clones'`.
- [ ] 1.2 Add `event_of(made, run_id, topic)` and read `Run.Started` and `Run.WorktreeMade` through it in both
  tests. Verify: both pass, and `uv run pytest packages/troupe/tests/test_run_workspaces.py` passes.

## 2. A killed perform is waited for itself (#405, design D3)

- [ ] 2.1 `perform_child.py` prints its own pid with `STARTED`, and every `STARTED` reader takes it. Verify:
  `test_run_queries.py`, `test_cli_runs.py`, `test_run_notices.py` and `test_run_workspaces.py` pass.
- [ ] 2.2 `Child.kill()` ends the perform's own pid if it's still running, then waits (bounded, naming the pid) until
  `is_running` says it has ended. The #405 test's assertion message carries the timings. Verify: a test checks that the pid
  `perform_child.py` reported has ended when `Child.kill()` returns.
  Run `uv run mypy --platform win32` on the changed files.
- [ ] 2.3 Run `scripts/flake_hunt.py --rounds 10 --load 2` (load under ~40 first) on `test_cli_runs.py`,
  `test_run_queries.py` and `test_run_workspaces.py`. Verify: no failures, and the counts are recorded in the PR.

## 3. Check and deliver

- [ ] 3.1 `uv run scripts/check.py` passes, its log kept in a scratch file. Verify: the log shows no failures.
- [ ] 3.2 Draft PR closing #402 and #405, with the threshold-0 failure on main and the flake hunt counts. Verify:
  `gh pr view` shows both `Closes`.

## Workflow follow-up

- Act on Claude's review of the last push; mark ready once clean, and check CI's Windows legs ran the #405 test.
- Ask the owner whether to also run the issue's flake hunt on Windows.
- `/opsx:archive` on the branch before the owner merges; after the merge, check #402 and #405 are closed and Done.
