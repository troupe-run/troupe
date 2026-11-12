# Tasks

## 1. Start and baseline

- [x] 1.1 Set troupe#362's and #365's cards to In Progress on the troupe roadmap board, and verify with
  `gh issue view <n> -R troupe-run/troupe --json projectItems`
- [x] 1.2 Write the regression test for #365 in `scripts/tests/test_guard_pytest_workers.py` (design D7: two scopes,
  one with a `conftest.py`, a clean selection by node id in one process and with `-n 2`, plus a third test with an
  untagged `docs/x.md` read). Run it against the current guard and verify the clean-selection case fails with the
  false `guard:` errors #365 describes and the untagged-read case fails as expected. Keep it uncommitted (it can't pass
  `scripts/check.py` until 3.3), saved under the scratchpad
- [x] 1.3 Before any theatre change, write the tests D3 requires against the current helpers and verify they pass on
  them: a `committed()` theatre has `git diff-files --name-only` empty; two theatres made in one test are independent
  (a commit in one doesn't appear in the other); each `make_repo` HOME is empty and separate; the scripts'
  `make_repo` repository has one commit and a clean status

## 2. Theatre templates (#362)

- [x] 2.1 In `gitrepo.py`, add the per-process template (D1, D2): a session-scoped autouse fixture that sets the
  template directory under `tmp_path_factory.getbasetemp()`, `make_repo` copying a template keyed by `(branch, refs)`
  with `shutil.copy` file times (D3), and building from scratch when no template directory is set. Load it with
  `-p gitrepo` in `pyproject.toml`'s `addopts`. Verify the 1.3 tests still pass, plus a test that a child process
  importing `gitrepo` without pytest builds from scratch
- [x] 2.2 Add `make_repo(..., fresh=True)` (D4), and make every repository in `test_git_state_cache.py` fresh by
  wrapping `make_repo` once at module level with `fresh=True`, its docstring naming what the file depends on. Verify
  with a test that `fresh=True` builds rather than copies (the build/copy counter from 2.5), and that
  `test_git_state_cache.py` passes in full
- [x] 2.3 Give `committed()` its own template, in `runtesting.py` beside `theatre()`, copied and then
  `git update-index --refresh`ed without `-q`, so a changed template fails the copy (D3). Verify the 1.3 `diff-files`
  test and all of `test_run_workspaces.py` pass
- [x] 2.4 Give `scripts/tests/conftest.py`'s `make_repo` a per-session template through `tmp_path_factory`, refreshed
  the same way. Verify the 1.3 scripts test and the scripts suite pass (`uv run scripts/check.py --scope scripts`)
- [x] 2.5 Add the build/copy counter (D5): each process writes `theatres-<pid>.json` into the directory
  `TROUPE_TEST_THEATRE_COUNTS` names, only when it's set, and a value that isn't an existing directory is refused with
  an error naming the variable and the fix. Verify with a pytester test of each: unset (nothing written), set (the
  process's counts), across two workers (a file per worker that made a repository), malformed (the error)
- [x] 2.6 Run the D4 audit over every caller of the four helpers, against the written list (racy window on the real
  clock, `st_mtime`/`st_ctime`/`.git` stats, commit and reflog times, SHAs compared across theatres), starting with
  `test_store_git.py`, `test_event_service.py`, `record_child.py`, `test_git_worktrees.py` and `test_config_files.py`.
  Each finding gets `fresh=True` and a comment naming its dependency; record the checked-and-not-dependent ones in a
  scratchpad note for the PR. Verify each changed file's tests pass
- [x] 2.7 Run the full suite three times with `-n 3 --dist worksteal` and once in one process (after telling the owner,
  load average below 20), and verify every run passes. Any failure is traced to its dependency and fixed by 2.6's rule
- [x] 2.8 Commit the theatre work in small steps (Conventional Commits, signed, `uv run scripts/check.py` passing
  before each), and verify `git log` shows each commit

## 3. Guard collection reads (#365, via troupe-run/infrastructure)

- [x] 3.1 Open an infrastructure issue on the troupe roadmap board (`--project "troupe roadmap"`) describing D6 and
  the reproduction, citing troupe#365 without a closing keyword. Verify it's on the board with `projectItems`
- [ ] 3.2 Make the change in troupe-run/infrastructure through its own workflow (its own branch, change and pull
  request), with its tests showing a selection by node id across two scopes passes, and a real untagged read in it
  still fails. Hand the pull request to the owner to merge, and verify its delivery commit
  (`chore(guard): deliver scripts/guard_pytest.py …`) is on troupe's `main`
- [ ] 3.3 Rebase this branch on `main` (and on #367 if it has merged), run the full check, and commit 1.2's test.
  Verify it now passes in one process and with `-n 2`, and that the #365 reproduction command (three tests across the
  troupe, vcs-git and runner-ollama suites) reports 3 passed and no errors

## 4. Measure (D5)

- [x] 4.1 Create a detached worktree of the merge base with `main` in the scratchpad for the baseline. Tell the owner
  before starting, and wait for a load average below 20. Run three interleaved pairs (baseline, variant) of
  `uv run pytest -n 3 -q --basetemp=<new empty dir> --durations=0`, writing each run's full output to a scratchpad
  file, and verify all six runs passed
- [x] 4.2 Record wall time, total setup time and build/copy counts for each run in design.md's "Measured" section. If
  any shape's copy wasn't faster than its build, revert that shape to building from scratch (and say so in D1), and
  verify the full check passes after
- [x] 4.3 Remove the baseline worktree this session created (after `lsof +D <path>` shows nothing using it), and
  verify `git worktree list` no longer lists it

## 5. Pull request

- [ ] 5.1 Open one draft pull request (`gh pr create --draft`) whose body closes #362 and #365, carries the measured
  numbers, the audit's results and the infrastructure pull request's link, and verify both issues show the PR as
  closing them
- [ ] 5.2 Act on Claude's review of the last push per CLAUDE.md, and mark the PR ready only when the review is clean.
  Verify every CI leg passes on Linux, macOS and Windows

## Workflow follow-up

- Archive the change on the branch (`/opsx:archive`) after the review requirements are met, with
  `openspec validate --strict` passing.
- Ask the owner to merge through the merge queue.
- After the merge: comment on #362 and #365 with the PR and the archived change, check both are closed and both cards
  say Done.
