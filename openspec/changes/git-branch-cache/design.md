# Design

## Context

See proposal.md, Why. Today (`packages/troupe-vcs-git/src/troupe_vcs_git/__init__.py`, after #367):

- `_current()` stats the files in `_WATCHED` plus the common `reftable/tables.list`, and the branch's own ref, and
  reuses the snapshot when they all match and it wasn't racy (cache-vcs-state D1, D3, D4).
- On a re-read it first reads the HEAD file for the ref it names (`_ref_named_by`) and stats that ref, then asks git
  (git-call-latency D4). Under reftable the HEAD file is a stub (`ref: refs/heads/.invalid`), so no name is known
  before git answers, and the table lists cover the refs.
- The short name comes from `rev-parse --abbrev-ref=loose HEAD` for a born HEAD and `symbolic-ref --short` for an
  unborn one, which agree (git-call-latency D4's differential test).

**Probe** (git 2.56, macOS, 2026-11-11; script in the session scratchpad). The checked-out branch is `refs/heads/<n>`.
Each row creates one thing, then reads `symbolic-ref --short HEAD` and `rev-parse --abbrev-ref=loose HEAD` (they
agree on every row but the last):

| Created | Files storage | Reftable |
|---|---|---|
| `refs/tags/<n>` (also nested, `a/b`) | `heads/<n>` | `heads/<n>`, through the table list |
| `refs/<n>` | `heads/<n>` | through the table list |
| root `<n>`, lower case (`main`): read from the **common** dir | `heads/<n>` | not read |
| root `<n>`, upper case (`FOO`): read from the **worktree's** git dir | `heads/<n>` | in the table |
| `refs/<n>` for `bisect/…`: read from the **worktree's** git dir | `heads/<n>` | in the table |
| `heads/<n>` at the root, with a tag `<n>` | `refs/heads/<n>` | n/a |
| a file `FETCH_HEAD` / `MERGE_HEAD`, branch of that name | `heads/<n>` | `heads/<n>`: special refs stay files |
| `refs/remotes/<n>`, `refs/remotes/<n>/HEAD` | unchanged (loose rules) | unchanged |
| a directory `refs/tags/<n>/` | unchanged | n/a |
| `refs/tags/<n>` as a symbolic ref to a missing ref | `symbolic-ref`: `gone` (!); `rev-parse`: `<n>` | |
| …and its target then created | `heads/<n>` | |

This is git's `shorten_unambiguous_ref` in loose mode: `<n>` is ambiguous if `<n>`, `refs/<n>` or `refs/tags/<n>`
resolves to an existing ref, and then `heads/<n>` is ambiguous if `heads/<n>` does. Where each name lives depends on
git's per-worktree rules for its syntax.

## Goals / Non-Goals

**Goals:**

- The token changes whenever git's short name for the branch could, on both ref storages and in linked worktrees, so
  a cached branch name is never stale. #75's rule stays: a cached value only while the token says nothing moved.
- A hit still runs no command.

**Non-Goals:**

- The racy window and the index watch (Decision #371, settled 2026-11-11: keep the rule as it is).
- Which form of the name lineage records (cache-vcs-state D2 stays: git's short name).
- `symbolic-ref --short` and `rev-parse --abbrev-ref=loose` disagreeing for a dangling symbolic ref named after the
  branch (last probe row). That predates this change (#367's single read), happens only with a hand-made symbolic
  ref, and isn't a staleness bug. It's #388: before the branch's first commit the adapter reports `gone`, and after
  it `feature`.

## Decisions

### D1: Watch every place git looks for a ref sharing the branch's name, in both directories

For a branch `refs/heads/<n>`, the token adds the stats of `<n>`, `heads/<n>`, `refs/<n>` and `refs/tags/<n>`, each
under both the worktree's git directory and the common directory (one set when they're the same, in the main
worktree). The worktree's git directory is the parent of the watched `HEAD` path; the common one is already known.

Both directories, rather than copying git's per-worktree rules: the probe shows the root name's directory depends on
its case, and `refs/<n>` on its first component (`bisect/`, `worktree/`, `rewritten/`). A stat of a path git doesn't
read costs microseconds and can only cause an extra read, never a stale one. That's four stats in the main worktree
and eight in a linked one, on every call.

**Stat, then read** (cache-vcs-state D1, git-call-latency D4) holds unchanged. The name comes from the HEAD file, read
before git is asked, and the paths are stat'd then. If git's answer names a different ref, HEAD moved during the read,
and the snapshot is already marked not reusable. On a hit, the paths come from the snapshot's ref.

**HEAD naming a ref outside `refs/heads/`.** git allows it (`git symbolic-ref HEAD refs/tags/x` succeeds), and its
short name follows other rules. Rather than watch those too, a snapshot read while HEAD names such a ref isn't
reused, as a racy one isn't: exact, and it costs a read per call only in that unusual state.

*Alternatives:*
- **Watch the `refs/tags` and `refs` directories' mtimes.** Misses nested names (`refs/tags/a/b` changes
  `refs/tags/a`), and every tag anywhere would cost a re-read.
- **Ask git for the paths (`--git-path`).** Exact, but the name changes with the branch, so it's a command on reads
  that today run none, or after the read, which breaks stat-then-read.
- **Accept and document the gap** (the issue's other option). It leaves lineage wrong, which #75's rule rules out.

### D2: Under reftable, watch the special refs

Reftable keeps every other ref in the tables, and the watched table lists change with them (the issue's table). Its
HEAD file names no branch, so D1's name-based paths aren't known before the read. The only loose files git reads
there are its special refs, `FETCH_HEAD` and `MERGE_HEAD`, in the worktree's git directory, and they matter only for
a branch named exactly that. The token watches those two files, whatever the branch. They're name-independent, so
they're stat'd before the read with the others. A fetch or merge changes them and costs a re-read: both also change
the index or HEAD's reflog in most cases, and the read is one process.

On the files storage those two are already among D1's paths when the branch has that name, so D2 applies under
reftable only (a common `reftable/tables.list` exists).

*Alternative:* the previous snapshot's branch name as the expected name, with a mismatch marked not reusable. It
costs an extra read for every new adapter on reftable, one per command, for a case that needs a branch called
`FETCH_HEAD`.

### D3: A symbolic ref named after the branch makes the read not reusable

When one of D1's paths holds a symbolic ref (`ref: …`), git's answer depends on whether its target exists, which
can be any ref anywhere. On a re-read, any D1 path that exists is read (a few dozen bytes), and if one starts with
`ref: `, the snapshot is marked not reusable, as a racy one is. Every call then reads again until the symbolic ref is
gone or replaced. Following the target instead would mean copying git's ref resolution, which D1 avoids.

### D4: The racy rule covers the new paths

D1's and D2's stats join the ones `_racy` looks at, so the rule stays "every watched file" (spec: a state read at a
racy time). Those files rarely exist, so this adds a re-read only just after one of them was written.

### D5: Tests, the reproduction first

In `packages/troupe-vcs-git/tests/test_git_state_cache.py`, against real repositories:

1. **The reproduction, written and run before the fix** (and seen to fail on the files storage):
   `test_a_ref_sharing_the_branchs_name_changes_the_cached_short_name`, parametrised over ref storage and the shapes
   that change the short name (`refs/tags/<n>`, `refs/<n>`, root `<n>`). A cached adapter whose clock is past the
   racy window reads, the ref is created with `git update-ref`, and the adapter's branch must equal git's
   `symbolic-ref --short`, and its token must have changed; then the ref is deleted and the same holds. git 2.56
   makes a lower-case root ref but refuses to delete it (`update-ref -d main`: "bad name"), so the tests delete that
   one as its file; under reftable there's no file, so that shape runs on the files storage only.
2. **The per-worktree and root shapes**: the same in a linked worktree, for a root name in upper case, `bisect/…`'s
   `refs/<n>`, `heads/<n>` behind a tag, and under reftable a branch `FETCH_HEAD` with the file written as git fetch
   writes it.
3. **The property test**: `Moves` gains `a_ref_named_after_the_branch(shape, add)`, creating or deleting a ref of a
   shape from `NAME_REFS` (plus root `<n>`) named after the current branch. The five machines keep their sizes
   (4 × 10), since the rule replaces nothing and each step costs the same.
4. **The symbolic ref**: with `refs/tags/<n>` a symbolic ref, two reads run git twice, and creating its target is
   seen on the next read. The test compares with a fresh adapter, not with `symbolic-ref --short` (#388).
5. **Cost unchanged**: the existing "repeated reads cost nothing" and racy-window tests keep passing.

## Risks / Trade-offs

- [A future git reads the name from somewhere else, or adds a special ref] → The property test and the
  per-shape tests run against the installed git on all three CI legs, so a new location fails them rather than
  leaving lineage quietly wrong.
- [More stats per call] → Four to ten `stat`s on a hit, against #367's ~11.7 ms per git process; they're microseconds
  and run no command.
- [A fetch costs a re-read under reftable] → One process, and only after a fetch.

## Migration Plan

None. Nothing persisted changes. Rolling back restores today's token.
