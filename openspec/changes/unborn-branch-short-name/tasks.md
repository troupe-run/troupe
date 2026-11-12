# Tasks

## 1. Tests that reproduce it first

- [ ] 1.1 Add a test in `packages/troupe-vcs-git/tests/test_git_state_cache.py`: the issue's repository (a tag
  `feature` symbolic to a missing `refs/heads/gone`, HEAD on an orphan `feature`). A fresh adapter reports `feature`
  before the first commit and after it. Parametrize it over files and reftable storage, and over the other shapes in
  the proposal's table (`refs/feature` dangling, a tag pointing at `main`, one at a missing `refs/tags/gone2`).
  Verify: it fails on main (`gone`, `heads/main`, `one2`) before any code change.
- [ ] 1.2 Change `gits_answers` and the `Names` invariant to D3's reference (born: `rev-parse --abbrev-ref=loose`;
  unborn: commit, read, `update-ref -d`), and add D3's symbolic-ref rule to `Names`. Verify: `TestNamesFiles` and
  `TestNamesReftable` fail on main with a symbolic-ref example before the code change.

## 2. The unborn read (D1, D2)

- [ ] 2.1 Replace `symbolic-ref --short` in `_read_unborn` with D1's walk and D2's command. Update the comments that
  name `symbolic-ref --short` as git's answer. Verify: 1.1 and 1.2 pass, on both storages.
- [ ] 2.2 Check the command counts: the existing unborn three- and four-command tests still pass unchanged.
- [ ] 2.3 Check git-branch-cache and #75 are intact: the token, watched-ref and symbolic-ref cache tests in
  `test_git_state_cache.py` pass unchanged (only their reference, per D3, may change), and the whole
  `packages/troupe-vcs-git` suite passes.

## 3. Verification

- [ ] 3.1 Run `Names` with many more examples than CI (a local hypothesis profile, both storages, a linked worktree
  layout as well). Verify: no failure, recorded in the PR.
- [ ] 3.2 Record the git version each CI leg runs (from the job logs) in the PR, with the legs' results for
  1.1 and `Names`. Verify: every leg passes.
- [ ] 3.3 `uv run scripts/check.py` passes.

## Workflow follow-up

- Draft PR closing #388; act on Claude's review; mark ready; archive on the branch; the owner merges.
- After the merge: comment on #388 with the PR and the archived change; check the issue is closed and its card Done.
- Raise with the owner whether to report the `symbolic-ref --short` buffer bug to the git project.
