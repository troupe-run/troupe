# Tasks

## 1. Tests that reproduce it first

- [x] 1.1 Add a test in `packages/troupe-vcs-git/tests/test_git_state_cache.py`: the issue's repository (a tag
  `feature` symbolic to a missing `refs/heads/gone`, HEAD on an orphan `feature`). A fresh adapter reports `feature`
  before the first commit and after it. Parametrize it over files and reftable storage, and over the other shapes in
  the proposal's table (`refs/feature` dangling, a tag pointing at `main`, one at a missing `refs/tags/gone2`).
  Verify: it fails on main (`gone`, `heads/main`, `one2`) before any code change.
- [x] 1.2 Change `gits_answers` and the `Names` invariant to D3's reference (born: `rev-parse --abbrev-ref=loose`;
  unborn: commit, read, `update-ref -d`), and add D3's symbolic-ref rule to `Names`. Verify: `TestNamesFiles` and
  `TestNamesReftable` fail on main with a symbolic-ref example before the code change.

- [x] 1.3 Add tests that pin the git behaviours D2 relies on, against a real repository, on both storages, with the
  git version in each failure: `rev-parse --symbolic-full-name` follows a symbolic ref (why the first D2 failed);
  `for-each-ref` lists a symbolic ref by its own name and leaves out a dangling one; with ambiguity warnings on, one
  match prints a name and two print nothing and exit 0, with an upper-case root ref and a symbolic ref among them.
  Verify: they pass locally (git 2.56) and on every CI leg (3.2).
- [x] 1.4 Add unborn cases with root refs (upper-case on both storages, with a remote, lower-case, `heads/<n>` at the
  root behind a tag, a lone remote, nothing shared). Verify: each reports the name git gives the branch once born.

## 2. The unborn read (D1, D2 as revised with the owner, 2026-11-12)

- [x] 2.1 Replace `symbolic-ref --short` in `_read_unborn` with D1's walk: `for-each-ref` for candidates under
  `refs/`, and every root candidate that may exist asked in one `rev-parse`, split by `--git-dir`. Update the comments
  that name `symbolic-ref --short` as git's answer. Verify: 1.1, 1.2 and 1.4 pass, on both storages.
- [x] 2.2 Command counts as the revised spec says: three when the files show the unborn HEAD, one more for the root
  candidates together, five at most otherwise. Verify: the unborn count tests pass, including a root ref on each
  storage (4, 5), reftable (5), and packed refs with two root candidates (5, which would have been 6).
- [x] 2.3 Check git-branch-cache and #75 are intact: the token, watched-ref and symbolic-ref cache tests in
  `test_git_state_cache.py` pass unchanged (only their reference, per D3, may change), and the whole
  `packages/troupe-vcs-git` suite passes. Verify: 228 passed.
- [x] 2.4 Add `vcs.short-name-undecided` to `troupe.core.errors`, both copies of `error.schema.json` and
  `contributing/event-store.md`, and a test that raises it with its details. Verify: the test passes.
- [x] 2.5 Replace the spec's requirement with one under a new name (a scenario name became false), and keep its
  requirement text under 500 characters. Verify: `openspec validate --strict` passes.

## 3. Verification

- [x] 3.1 Run `Names` with many more examples than CI (a local hypothesis profile, both storages, a linked worktree
  layout as well). Verify: no failure, recorded in the PR.
- [ ] 3.2 Record the git version each CI leg runs (from the job logs) in the PR, with the legs' results for
  1.1, 1.3 and `Names`. Verify: every leg passes.
- [x] 3.3 `uv run scripts/check.py` passes.

## Workflow follow-up

- Draft PR closing #388; act on Claude's review; mark ready; archive on the branch; the owner merges.
- After the merge: comment on #388 with the PR and the archived change; check the issue is closed and its card Done.
- Raised with the owner whether to report the `symbolic-ref --short` buffer bug to the git project: not to (owner,
  2026-11-12).
