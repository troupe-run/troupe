# Proposal

## Why

Recording an event runs two `git` processes, `symbolic-ref` and `rev-parse`, to stamp the branch and HEAD into its
lineage (`EventStore.vcs_state`). That's about 60 ms, roughly 90% of what recording an event costs (measured in #54).
troupe-run/troupe#75 asks for no `git` process in the common case, with lineage exactly as accurate as now.

The obvious fix is to cache behind `branch_token()`, which the text store already uses for reads. It isn't safe yet.
Probing git 2.56 for this proposal showed that the token misses moves it is documented to catch:

| Repository | Missed by today's token |
|---|---|
| files refs, `core.logAllRefUpdates=false` | commit, `reset --soft`, `update-ref` of the branch |
| reftable refs (git 3.0's default), reflogs on or off | commit, `reset --soft`, `update-ref`, detaching HEAD |

A cache behind that token would stamp the wrong HEAD, and on reftable the wrong branch. The read side already has
this bug: a reftable theatre that detaches HEAD keeps reading as if on its branch. So the token has to cover more
before anything can rely on it. A wider token watching `packed-refs`, the branch's own ref and both
`reftable/tables.list` files caught every case in the same probe.

## What Changes

- **The git adapter's token covers every move of the branch or HEAD**, by any process and with either ref storage. It
  stats the files git changes when either moves: `HEAD`, the index, `logs/HEAD`, `packed-refs`, the checked-out
  branch's loose ref, and the worktree's and common `reftable/tables.list`. It still runs no command while nothing
  has moved.
- **The git adapter caches the branch and HEAD behind that token.** `branch()` and `head()` run git only when the
  token has changed since they last read. A change runs at most three commands, however many events follow.
- **Racy timestamps are distrusted, as git distrusts its own index.** A state read while a watched file was modified
  within a named window (`GIT_RACY_WINDOW_SECONDS`) is read again on the next call. Two git operations in one
  timestamp tick, leaving a file the same size and on a reused inode, then can't hide a move.
- **The port's contract says what a token must cover.** `Vcs.branch_token` changes whenever the branch or HEAD
  changes, by this process or another. An adapter may cache `branch()` and `head()` only behind it.
- **The plain filesystem adapter** already runs no command. Its contract and cost are now tested alongside git's.
- **A read-side bug is fixed too.** The text store reads the branch only when the token changes. In a reftable
  theatre that detaches HEAD, it keeps reading events as if HEAD were still on the branch: another branch's
  uncommitted segment is left out wrongly, and the store keeps appending to the branch's segment. Reads only need the
  branch, plus the committed set that the index already covers, so the misses with reflogs off don't affect reads.
  The wider token fixes it, and a regression test (task 4.4) proves it. The PR says so, because #75 lists reads as
  out of scope.

Not changing: the reported branch name is still git's `--short` form, and lineage's shape is the same. The identity
chain's `git config` read, once per command, is out of scope: config spans includes and several files, and the issue
is about the branch and HEAD. `logs --follow`'s latency (#74) is out of scope too.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `vcs`: adds what the branch token must cover, that the git adapter reads the branch and HEAD only when it has
  changed, and the racy-timestamp rule.
- `event-store`: adds that recording events runs no `git` command while the branch and HEAD haven't moved.

## Impact

- `packages/troupe-vcs-git/src/troupe_vcs_git/__init__.py` (token, cache) and `defaults.py` (the racy window).
- `packages/troupe/src/troupe/core/vcs.py`: the port's docstrings, which are its contract.
- `packages/troupe-vcs-git/tests/`: the token's existing cost test now allows the commands a change runs. New
  scenario tests, plus a differential test against an uncached adapter over git operations and both ref formats.
- `packages/troupe/tests/` or `packages/troupe-store-text/tests/`: lineage after git operations, in one session and
  in a long-lived second process; the cost of recording N events with each adapter.
- No dependency, schema or CLI change. `EventStore.vcs_state` is unchanged: it calls `branch()` and `head()`, which
  are now cheap.
