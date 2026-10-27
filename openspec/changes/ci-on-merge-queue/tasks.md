# Tasks

## 1. Declare `pyyaml` (design D2)

- [x] 1.1 Add `pyyaml` and `types-PyYAML` to the root `dev` dependency group in `pyproject.toml`, with lower bounds
  matching the versions `uv lock` resolves, and run `uv lock`. Verify `uv sync --locked` succeeds and
  `uv run python -c "import yaml"` works, and that `uv.lock`'s diff adds only those two to the root's dev group (and
  the stubs' entry).

## 2. The test, before the trigger (design D2)

- [x] 2.1 Write `scripts/tests/test_ci_workflow.py`, with a module docstring citing the spec (quality-check) and this
  design. Three tests, named for what they check, as D2's table has them: CI runs on merge groups; no trigger filters
  by path; only `changes` reads the event, and only on pull requests. Look the triggers up under `True` with a comment
  on PyYAML's YAML 1.1 reading of `on`. Each failure names `.github/workflows/ci.yml`, what was found and what would
  skip the check on the queue. Verify the first test fails on this branch before 2.2, and the other two pass (they
  hold on `main` today).
- [x] 2.2 Check each test can fail: in a scratch copy of `ci.yml` (in a temporary directory, through a helper that
  takes the path), add `paths: [src/**]` under `pull_request`, change `changes`' `if` to also allow `merge_group`, and
  add `if: github.event_name != 'merge_group'` to `check-legs`. Keep these as parametrized cases in the test file, so
  they stay checked. Verify each case fails with its message, and `uv run pytest scripts/tests/test_ci_workflow.py`
  shows only the merge-group test failing.
- [x] 2.3 Verify `printf 'scripts/tests/test_ci_workflow.py\n' | uv run --no-project scripts/guard.py check-scope`
  answers `scope=scripts`, and the reach check (`uv run scripts/check_paths_reach.py`) agrees with the declaration.

## 3. The trigger and the comment (design D1, D3)

- [x] 3.1 Add `merge_group:` to `on` in `.github/workflows/ci.yml`, after `pull_request`, with no `types`. Verify
  `uv run pytest scripts/tests/test_ci_workflow.py` passes in full.
- [x] 3.2 Add D3's paragraph to the workflow's header comment, and add `merge_group` to the `check-legs` comment that
  says when the legs get no answer ("a push to main, a merge group, or a failed `changes`"). Verify the comment names
  `scripts/tests/test_ci_workflow.py`, and `uv run scripts/python_versions.py` (or the test that runs it) still finds
  exactly one matrix line.
- [x] 3.3 Run `uv run scripts/check.py` and commit (`ci: run the full check on merge queue commits`), with the test
  and the dependency from groups 1 and 2 in their own earlier commits if they were committed separately.

## 4. On the pull request

- [ ] 4.1 Open the pull request with `Closes #180`. Verify every required check (`check`, `guard (workflow rules)`,
  `DCO`) passes on Linux, macOS and Windows, and that the run's `check` job log says every leg passed.

## Workflow follow-up

- Archive the change on the branch before merging (`/opsx:archive`), then merge.
- After the merge, comment on #180 with the PR and the archived change, and check the issue is closed and its card on
  the troupe roadmap board says Done.
- Comment on troupe-run/infrastructure#169 that troupe's `check` now reports on merge groups, so its queue can be
  declared. The first pull request through troupe's queue is the end-to-end check (design, Risks), verified there.
