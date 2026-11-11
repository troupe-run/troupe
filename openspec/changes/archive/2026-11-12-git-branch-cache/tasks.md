# Tasks

Every commit is signed and signed off (`git commit -S -s`), and `uv run scripts/check.py` passes before it.

## 1. Reproduce #370 first

- [x] 1.1 Add `test_a_ref_sharing_the_branchs_name_changes_the_cached_short_name` (design D5 test 1) to
  `packages/troupe-vcs-git/tests/test_git_state_cache.py`, over both ref storages and `refs/tags/<n>`, `refs/<n>` and
  root `<n>`, creating then deleting the ref. Run it on the unchanged adapter and record which cases fail (expected:
  every files-storage case; reftable passes). Verify: the failing output, quoted in the commit message.
- [x] 1.2 Add the `a_ref_named_after_the_branch` rule to `Moves` (D5 test 3) and run the five `TestMoves…` machines on
  the unchanged adapter. Verify: the files-storage machines fail with a stale short name (or, if Hypothesis doesn't
  reach it in 4 × 10, say so in the commit and rely on 1.1 as the reproduction).

## 2. Watch the refs that share the branch's name

- [x] 2.1 In `troupe_vcs_git/__init__.py`, stat D1's paths (`<n>`, `heads/<n>`, `refs/<n>`, `refs/tags/<n>`, under the
  worktree's git dir and the common dir, deduplicated) from the HEAD file's ref before the read, and from the
  snapshot's ref on a hit; keep them in `_State` and its token; include them in `_racy` (D4). Verify: 1.1 and 1.2 pass
  on both storages, and every existing test in `test_git_state_cache.py` and `test_git_adapter.py` passes.
- [x] 2.2 Under reftable, also watch `FETCH_HEAD` and `MERGE_HEAD` in the worktree's git dir (D2). Verify: D5 test 2's
  reftable `FETCH_HEAD` case, written first and seen to fail, then passes.
- [x] 2.3 Add D5 test 2's remaining cases (linked worktree, upper-case root, `bisect/…`, `heads/<n>` behind a tag).
  Verify: each passes; each fails on the unchanged adapter; and with D1's paths limited to the common dir (a
  mutation check, not committed), the two git reads from the worktree's own directory (upper-case root, `bisect/…`)
  fail.
- [x] 2.4 Mark a snapshot not reusable when a D1 path holds a symbolic ref (D3), with D5 test 4. Verify: the test
  fails before the change and passes after.
- [x] 2.5 Update the module docstring and `_WATCHED`'s comment to name the new paths and cite this change's design.
  Verify: `uv run scripts/check.py` passes (ruff, mypy --strict, the full suite).

## 3. Integration

- [x] 3.1 Push, open the draft pull request (`Closes #370`), and act on Claude's review of the last push. Verify: the
  review leaves no must-fix or decision open, then all three CI legs pass once it's marked ready.

## Workflow follow-up

- Archive the change on the branch before the owner merges; after the merge, comment on #370 with the pull request
  and the archived change, and check its card says Done.
