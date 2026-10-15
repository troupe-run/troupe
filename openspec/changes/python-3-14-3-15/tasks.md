# Tasks

## 1. Make the tests version-independent, then widen

- [x] 1.1 Rewrite `scripts/tests/test_python_versions.py` and `scripts/tests/test_on.py` to read the bound and the
  supported versions from the repository (design D3). Verify all of `uv run pytest scripts/tests` passes against
  the current `>=3.12,<3.14`. Then verify the same tests pass in a scratch copy widened to `<3.16`, where 19 failed
  before
- [x] 1.2 Widen `requires-python` to `>=3.12,<3.16` in all nine `pyproject.toml` files, set `ci.yml`'s matrix to
  `["3.12", "3.13", "3.14", "3.15"]`, and re-lock (design D1). Verify `uv sync --locked` succeeds,
  `uv run pytest scripts/tests` passes, and `uv.lock`'s diff only adds 3.14+ wheels and `resolution-markers`
- [ ] 1.3 After the PR's first CI run, record every 3.14 and 3.15 job's result, and whether the macOS 3.15 jobs built
  `grimp` from source (design D5). Investigate any failure before the PR is ready, and record it in design.md

## 2. Fix what 3.14 and 3.15 break

- [x] 2.1 Choose the race test's exit watcher by `hasattr(os, "waitid")` instead of `sys.platform == "linux"`
  (design D2), and update its docstrings to say who reaps on which version. Verify
  `test_a_kill_sent_after_the_child_exited_but_before_asyncio_saw_it_did_not_end_it` passes on 3.12, 3.13, 3.14 and
  3.15 here (`uv run scripts/on.py <v> pytest packages/troupe/tests/test_platform_processes.py`). Then verify, by
  temporarily forcing each helper, that the `waitid` helper fails the precondition on a child that never exits
  (mutation check)
- [ ] 2.2 Wrap the `FileType` construction in `test_cli.py`'s file-type case in
  `pytest.warns(PendingDeprecationWarning)` on 3.14 and later (design D4). Verify the test passes on all four
  versions and the warning no longer appears in the 3.14 and 3.15 test summaries

## 3. Docs

- [ ] 3.1 Update the README's supported versions to 3.12–3.15 and its `requires-python` example to
  `>=3.12,<3.16`. Verify each command in the section runs as written, including `uv run scripts/on.py 3.15 python -V`

## 4. Integration

- [ ] 4.1 Run the full `scripts/check.py` on 3.12 (plain `uv run`), then on 3.13, 3.14 and 3.15 through
  `scripts/on.py`, one after another, each to a pass. Then run `openspec validate python-3-14-3-15 --strict`
  to a pass

## Workflow follow-up

- Open the PR with `Closes #107`. Keep any other issue number out of closing phrases in commits and the PR body.
- Archive on the branch before merging. After merging, check that #107 is closed and its card says Done, and comment
  on #107. Close #104, the parent, with both sub-issues done, and check that its card says Done too.
- Tell infrastructure#43 the new job names, so they can be made required.
