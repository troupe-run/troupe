# Proposal

## Why

The git adapter can report a stale branch name, and lineage records it (#370). git's short name for the checked-out
branch depends on which other refs share its name: once a tag `main` exists, `main` becomes `heads/main`. The branch
token (cache-vcs-state design D3) watches HEAD, the index, HEAD's reflog, `packed-refs`, the branch's own ref and the
reftable lists. A new loose tag is none of these, so with the files ref storage the adapter keeps saying `main` until
something else moves. Deleting the tag goes stale the same way in reverse. That breaks #75's rule: a cached value is
used only while its token says nothing has moved.

## What Changes

- The token also watches the files git reads to decide the short name: for a branch `refs/heads/<n>`, the loose refs
  `<n>`, `heads/<n>`, `refs/<n>` and `refs/tags/<n>`, in both the worktree's git directory and the common one. The
  paths come from the ref named in the HEAD file, which is read before git is asked (git-call-latency design D4), so
  they're stat'd before the read, as every watched file is.
- Under reftable those refs live in the tables, whose lists are already watched. The only loose files git reads there
  are its special refs, `FETCH_HEAD` and `MERGE_HEAD`, which matter for a branch with that exact name. The token
  watches those two in the worktree's git directory.
- When one of those refs is a symbolic ref, the short name depends on its target, which the token can't see. A
  snapshot read while one exists isn't reused, so every call reads again until it's gone.
- A test that fails on `main` reproduces #370 first: on both ref storages, creating and then deleting a ref named
  after the checked-out branch, with the adapter's clock past the racy window. The state-cache property test (the
  `Moves` machines) gains that operation.
- #75's rule is unchanged: the racy window and the index watch stay as they are. Decision #371 settled that
  (owner, 2026-11-11), so nothing of it is built here.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `vcs`: the branch token changes when the branch's short name does, including when a ref sharing its name is
  created or deleted; the cached-answers scenario includes that operation.

## Impact

- `packages/troupe-vcs-git/src/troupe_vcs_git/__init__.py`: `_State`, `GitAdapter._current()` and the paths it stats.
- Tests: `packages/troupe-vcs-git/tests/test_git_state_cache.py`.
- A stat costs microseconds; a hit now takes four to ten more stats and still runs no command. No new settings, and
  no protocol, config, event or lineage format changes. No spec Purpose changes, so troupe-run/infrastructure's
  `oob/troupe-spec-purposes.json` needs no update.
- Closes troupe-run/troupe#370.
