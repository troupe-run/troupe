# Proposal: an unborn branch keeps the short name it will have after its first commit

## Why

When a symbolic ref named after the checked-out branch exists, the git adapter reports one branch before the branch's
first commit and another after it, so lineage records the branch changing name when it didn't (troupe-run/troupe#388).

The cause is a git bug, wider than the issue says. Since #367 the adapter reads a born HEAD's short name with
`rev-parse --abbrev-ref=loose`, and an unborn one with `symbolic-ref --short`. `symbolic-ref --short` shortens a name
that git's own ambiguity check overwrites whenever that check follows a symbolic ref. So it's wrong for any symbolic
ref sharing the branch's name, dangling or not. Probed on git 2.56, files and reftable storage, branch `feature`:

| A ref sharing the name | `symbolic-ref --short` | `rev-parse --abbrev-ref=loose` (after a commit) |
|---|---|---|
| `refs/tags/feature` → missing `refs/heads/gone` | `gone` | `feature` |
| `refs/feature` → missing `refs/heads/gone` | `gone` | `feature` |
| `refs/tags/feature` → existing `refs/heads/main` | `heads/main` | `heads/feature` |
| `refs/tags/feature` → missing `refs/tags/gone2` | `one2` | `feature` |
| a plain tag `feature`, no symbolic ref | `heads/feature` | `heads/feature` |

`rev-parse --abbrev-ref=loose` is right on every row, but it refuses an unborn ref, even by its full name. No git
command shortens an unborn branch's name correctly when a symbolic ref shares it.

## What Changes

- **git's short name is what `rev-parse --abbrev-ref=loose` reports**, not `symbolic-ref --short`. The spec, the
  differential tests and the code comments that name `symbolic-ref --short` as the reference change to it.
- **An unborn branch's short name is shortened by git's own rule, using what git finds.** The adapter still reads the
  unborn branch's full name with `symbolic-ref --quiet HEAD`, which is right. It then shortens it with git's loose
  rule (`<n>` unless a root `<n>`, `refs/<n>` or `refs/tags/<n>` exists, then `heads/<n>` unless a root `heads/<n>`
  exists). Which of those refs exist comes from git itself, in one command, as git resolves them: a dangling symbolic
  ref doesn't count, on either ref storage, in any worktree (design D1, D2).
- **The command counts don't change**: three commands for an unborn HEAD whose files show it, four otherwise.
- **A test that reproduces it first**: the issue's repository, checked before and after the branch's first commit,
  fails on main. The names property test (`Names` in `test_git_state_cache.py`) adds symbolic refs, dangling and not,
  and checks an unborn read against the name the branch has once it's born.
- **Unchanged**: #75's rule (a cached value only while the token says nothing moved), and the git-branch-cache
  change's watched refs and its re-read on every call while a symbolic ref shares the name under the files storage.

An earlier option, raised with the owner on 2026-11-12, was to refuse when a root ref named after the branch exists,
because no existence check then known agreed with git for a root ref. The probe then found one that does
(design D2), so nothing is left to refuse, and there's no new error.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `vcs`: "The git adapter re-reads the branch and HEAD with one command once HEAD has a commit" names
  `rev-parse --abbrev-ref=loose` as git's short name, and says an unborn branch reports the short name it will have
  once it has a commit, with a scenario for a symbolic ref sharing its name.

## Impact

- `packages/troupe-vcs-git/src/troupe_vcs_git/__init__.py`: the unborn read (`_read_unborn`) and comments.
- `packages/troupe-vcs-git/tests/`: `test_git_state_cache.py` (`Names`, `gits_answers`, the symbolic-ref tests) and the
  git-call-latency differential test, whose reference changes.
- No Purpose changes, so no `oob/troupe-spec-purposes.json` update in infrastructure.
