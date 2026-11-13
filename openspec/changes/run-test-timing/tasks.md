# Tasks

## 1. Worktree events found by topic (#402, design D1, D2)

- [x] 1.1 Write the threshold-0 pin first (D2): the #402 test's body with `WORKSPACE_ANNOUNCE_AFTER_SECONDS` at 0,
  asserting a `workspace.waiting` was recorded before `Run.WorktreeMade`. Verify: it fails on the current test body
  with `KeyError: 'clones'`.
- [x] 1.2 Add `event_of(made, run_id, topic)` and read `Run.Started` and `Run.WorktreeMade` through it in both
  tests. Verify: both pass, and `uv run pytest packages/troupe/tests/test_run_workspaces.py` passes.
- [x] 1.3 `test_event_payloads.py`'s worktree-run test, which failed at the threshold of 0 too, compares topics less
  `Run.Noticed`, allows only `workspace.waiting` there, and runs at 0 as well. Verify: every `packages/troupe` test
  file that mentions worktrees passes with the threshold at 0 for every test.

## 2. A killed perform is waited for itself (#405, design D3)

- [x] 2.1 `perform_child.py` prints its own pid with `STARTED`, and every `STARTED` reader takes it. Verify:
  `test_run_queries.py`, `test_cli_runs.py`, `test_run_notices.py` and `test_run_workspaces.py` pass.
- [x] 2.2 `Child.kill()` ends the perform's own pid if it's still running, then waits (bounded, naming the pid) until
  `is_running` says it has ended. The #405 test's assertion message carries the timings. Verify: a test checks that the pid
  `perform_child.py` reported has ended when `Child.kill()` returns.
  Run `uv run mypy --platform win32` on the changed files.

## 3. A held lease whose holder has ended is interrupted (design D4)

- [x] 3.1 Write the tests first (D4, "Testing it on every OS"): a helper holds the lease lock while `perform.pid`
  names an ended process, and `status` and `logs` say `interrupted`; with a live pid, no file, or a malformed file,
  they say `running`. Verify: the ended-pid test fails on the current `lease_state`, saying `running`, and the
  others pass.
- [x] 3.2 `perform` writes `perform.pid` through `replace_file` once it holds the lease, before the start is
  recorded. Verify: a test reads the pid file of a live `Child` and finds the pid `perform_child.py` reported.
- [x] 3.3 `lease_state` reads the pid when the lock is held, as D4 says. Verify: 3.1's tests all pass, and so do
  `test_run_queries.py`, `test_cli_runs.py`, `test_run_notices.py` and `test_run_changes.py`.
- [x] 3.4 `contributing/runs.md`'s lease step and state table say what the pid file is for. Verify: the table's
  `running` and `interrupted` rows match D4.

## 5. The pid's namespace token (design D4, D5; owner decision 2026-11-13, from #410's review)

- [x] 5.1 Tests first: `test_platform_processes.py` checks a child's token equals its parent's, a token read twice is
  the same, and it holds the boot id (Linux) or the host name (macOS, Windows). `test_run_queries.py` writes the
  reader's token with the ended pid, and adds cases that read `running`: a different token, no token. Verify: the
  new tests fail before 5.2 and 5.3 (no `namespace_token`; a different token reads `interrupted`).
- [x] 5.2 `namespace_token()` in `troupe.platform.processes`, per OS as D5 says. Verify: 5.1's platform tests
  pass, and `uv run mypy --strict --platform win32` and `--platform linux` pass on `processes.py`.
- [x] 5.3 `perform` writes the token after the pid, and `lease_state` trusts "ended" only with a token equal to its
  own. `contributing/runs.md` and `contributing/platform.md` say so. Verify: 5.1's tests pass, and so do
  `test_run_queries.py`, `test_cli_runs.py`, `test_run_notices.py` and `test_run_changes.py`.
- [ ] 5.4 `uv run scripts/check.py` passes, and the push gets a fresh review. Verify: the log shows no failures.

## 4. Check and deliver

- [x] 4.1 `uv run scripts/check.py` passes, its log kept in a scratch file. Verify: the log shows no failures.
- [x] 4.2 Run `scripts/flake_hunt.py --rounds 10 --load 2` (load under ~40 first) on `test_cli_runs.py`,
  `test_run_queries.py` and `test_run_workspaces.py`. Verify: no failures, and the counts are recorded in the PR.
- [x] 4.3 Draft PR closing #402 and #405, with the threshold-0 failure on main and the flake hunt counts. Verify:
  `gh pr view` shows both `Closes`.

## Workflow follow-up

- Act on Claude's review of the last push; mark ready once clean, and check CI's Windows legs ran the #405 test.
- The PR records that CI's Windows legs are the Windows check (owner decision, 2026-11-13; as #407 did for #406).
- `/opsx:archive` on the branch before the owner merges; after the merge, check #402 and #405 are closed and Done.
