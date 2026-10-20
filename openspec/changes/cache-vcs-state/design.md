# Design

## Context

See proposal.md, Why. What exists today:

- **`EventStore.vcs_state`** (`packages/troupe/src/troupe/core/events/service.py`) calls `vcs.branch()` and
  `vcs.head()` for every event recorded, through `Command`, `record_reaction` and the file-event path.
- **`GitAdapter.branch()`** runs `git symbolic-ref --quiet --short HEAD`, and **`head()`** runs
  `git rev-parse --verify --quiet HEAD`. Neither caches. `committed_under` also calls `head()`.
- **`GitAdapter.branch_token()`** runs `git rev-parse --git-path HEAD --git-path index --git-path logs/HEAD` once per
  adapter, then returns `(st_mtime_ns, st_size, st_ino)` for each of those three files. Its docstring on the port
  already promises that it "changes whenever the branch, HEAD or what is committed might have".
- **`TextStore.refresh`** compares the token on every read and insert. It calls `branch()` again only when the token
  changes, and keeps its own `_branch`.
- **`FilesAdapter`** returns `None` for the branch, HEAD and token, and runs no command.

Probe (git 2.56, this machine; script in the session scratchpad). After each operation, did the token change?

| Operation | files, reflogs on | files, reflogs off | reftable, either |
|---|---|---|---|
| `commit --allow-empty` | yes | **no** | **no** |
| `reset --soft HEAD~` | yes | **no** | **no** |
| `update-ref` of the branch | yes | **no** | **no** |
| switch to a same-tree branch | yes | yes | yes |
| detach | yes | yes | **no** |

Adding `packed-refs`, the branch's loose ref (`<common-dir>/refs/heads/<name>`), the worktree's
`reftable/tables.list` and `<common-dir>/reftable/tables.list` made every row "yes". In a reftable linked worktree,
`--git-path reftable/tables.list` resolves to the worktree's own table list, which holds HEAD. The branches are in the
common directory's list, so both are needed.

## Goals / Non-Goals

**Goals:**
- The token covers what the port says it covers (spec: vcs). The cache is no more likely to be wrong than git's own
  index check.
- One place owns the cache: the adapter that knows which files git changes.
- No behaviour change except speed, and the read-side fix that comes with the wider token. Same branch form, same
  lineage shape, same errors.

**Non-Goals:**
- Caching `configured_identities` (`git config`, once per command when no actor is given). Config spans the system,
  global, local and worktree files and their includes, so a token for it is a different design.
- Caching `committed_under`. The text store already caches it per token.
- Watching files instead of statting them. A stat on each call is cheap. Watching is #74's subject.

## Decisions

### D1: The cache lives in the git adapter, not in `EventStore`

`GitAdapter` keeps one immutable snapshot: the watched files' stats, the branch's ref path and its stat, the branch,
HEAD, and whether the read was racy (D4). `branch()`, `head()` and `branch_token()` all go through one private method
that returns a fresh snapshot:

1. Stat the fixed files. If they match the snapshot's, the ref file's stat matches, and the snapshot isn't racy,
   return it. No command runs.
2. Otherwise, read again in this order: stat the fixed files, run `symbolic-ref --quiet HEAD` (the full ref name, for
   its path), stat that ref, then run `symbolic-ref --quiet --short HEAD` and `rev-parse --verify --quiet HEAD`.
   Store the new snapshot.

The rule is to **stat before reading**. A move that lands during the read leaves a stat older than the values, so the
next call reads again. It never leaves values older than the stat. At worst that costs one extra read, and it can't
leave a stale answer.

`branch_token()` returns the snapshot's key: the fixed stats, the ref stat, the branch and HEAD. That key changes only
when the values or the watched files did. Putting the values in the key means a racy re-read (D4) that finds nothing
changed doesn't make the text store rebuild its index.

*Alternatives:*
- **Cache in `EventStore.vcs_state`, behind `branch_token()`.** That's generic over adapters, but the token can't name
  the branch's ref file until the branch has been read. The first token would leave the ref out, and the next would
  include it, so every new branch would cost one spurious re-read and one index rebuild in the text store. The
  stat-before-read order also needs the adapter's help. The service stays unchanged instead.
- **Read `HEAD`'s contents directly to find the branch's ref.** Under reftable, `HEAD` is a stub
  (`ref: refs/heads/.invalid`), so this would parse git internals that differ by backend. troupe only stats git's
  files and asks git for answers.

### D2: The short name costs a separate command

The reported branch stays `symbolic-ref --short`'s answer. That is `heads/main`, not `main`, when a tag `main` also
exists. The ref's path needs the full name. No single local command prints both for an unborn HEAD (`rev-parse
--symbolic-full-name HEAD` fails before the first commit), so a re-read runs three commands where it ran two. That
happens only when something moved. Dropping `--short` and stripping `refs/heads/` would change what lineage records
for ambiguous names. That might be the better rule, but it's a behaviour change for a separate issue.

### D3: What the token watches

These are resolved once per adapter with one command, `git rev-parse --git-common-dir --git-path HEAD --git-path index
--git-path logs/HEAD --git-path packed-refs --git-path reftable/tables.list`. The probe table shows why each is there:

| File | Catches |
|---|---|
| `HEAD` (per worktree) | switch, detach, a commit while detached (files refs) |
| `index` (per worktree) | add, and most commits, switches, merges and resets |
| `logs/HEAD` (per worktree) | every move of HEAD, when reflogs are on |
| `packed-refs` (common) | `pack-refs`, and a packed branch moving |
| `<common>/refs/heads/<name>` | a commit or reset with reflogs off, and another worktree moving this branch |
| `reftable/tables.list` (per worktree) | HEAD moves under reftable |
| `<common>/reftable/tables.list` | branch moves under reftable |

A file that doesn't exist stats as `None`, so files-backend repositories pay one failed stat for the reftable paths,
and the other way round. Paths come from git (`--git-path`, `--git-common-dir`), so a linked worktree, a `.git` file
and a separate git dir all work. `stat` also has to treat `NotADirectoryError` as missing: under reftable,
`refs/heads` is a file, so a path below it fails that way (seen in the probe).

### D4: Racy timestamps

This is git's own "racily clean" rule. When a snapshot is read, if any watched file's `st_mtime_ns` is within
`GIT_RACY_WINDOW_SECONDS` of the wall time at the start of the read, the snapshot is marked racy and isn't reused.
Without the rule, two git operations inside one timestamp tick could leave a file with the same mtime, the same size
(a loose ref is always 41 bytes) and, after a lock-and-rename, a reused inode. The token would then hide the second
operation until something else moved.

The window follows the file system's timestamp resolution, read from the watched files themselves. When every
watched file that exists has an mtime of whole seconds (`st_mtime_ns % 1_000_000_000 == 0`), the file system keeps
coarse timestamps (FAT's 2 s, HFS+'s 1 s), and the window is `GIT_COARSE_RACY_WINDOW_SECONDS`, **2.0 s**. Otherwise
it is `GIT_RACY_WINDOW_SECONDS`, **0.1 s**. That's well above the clock tick that fine timestamps are taken from
(about 4 ms on Linux and 16 ms on Windows; nanoseconds on APFS). A fine file system whose every watched file happens
to land on a whole second just gets the safer window. Both are named settings in `troupe_vcs_git/defaults.py` and
constructor parameters, like the timeout. A clock is injected (`now`, defaulting to `time.time_ns`) so tests can
control the window without sleeping.

The cost: for the window after a git operation, every read of the token runs three commands. Reads cost none on
`main`, so this does cost reads. A first version used 2 s everywhere, and `logs --follow`'s first event from a child
process arrived about 0.8 s later (`test_following_from_another_process_sees_each_event_and_stops_at_the_end`
failed), because the text store reads the token many times per event. With 0.1 s, that cost is confined to a tenth
of a second after each git operation on every file system troupe supports (owner, 2026-10-20).

*Alternative:* trust the stat alone, as today's read side does. The probe shows reflogs-on repositories always grow
`logs/HEAD`, but with reflogs off or reftable the race is real. "Exactly as accurate" rules it out.

### D5: The port's contract (docstrings in `troupe/core/vcs.py`)

- `branch_token`: changes whenever the branch, HEAD or what is committed changes, by this process or any other.
  Reading it runs no command while nothing has moved. An adapter that can't promise that SHALL return a value that
  never compares equal, such as a fresh `object()`, which turns caching off for its callers.
- `branch` / `head`: report the state at the time of the call. An adapter may answer from a cache only while its
  token is unchanged.

The plain filesystem adapter already meets this. Its token is a constant `None`, and its branch and HEAD are always
`None`.

### D6: Thread safety

The snapshot is one immutable object, replaced by a single attribute assignment. Two threads that both find it stale
both re-read, and the last write wins. Both values are correct for some moment during the call, which is what the
uncached adapter promised. There's no lock, so no new wait.

### D7: Tests

In `packages/troupe-vcs-git/tests/` (new `test_git_state_cache.py`), against real repositories (`gitrepo.Repo`):

1. **Token scenarios**, parametrised over ref storage (files, reftable) × reflogs (on, off): commit, empty commit,
   switch to a same-tree branch, detach, a commit while detached, `reset --soft/--mixed/--hard`, merge, `update-ref`
   from a linked worktree, `pack-refs --all` then a commit. Each asserts that the token changed and that `branch()`
   and `head()` equal a fresh adapter's. The adapter is built with `now` set far ahead, so nothing is racy and the
   stat logic alone is tested.
2. **Differential (stateful hypothesis) test** over the same matrix. It runs random sequences of the operations
   above plus `branch -m` of the current branch. After each step it compares the cached adapter's `branch()` and
   `head()` with a new `GitAdapter`'s. This is the "behaviour unchanged" check the learned rule asks for. The new
   path is compared with the old path, which the fresh adapter still is. It also runs once with the real clock and
   the default window, so the shipped configuration is covered too.
3. **Cost**: repeated reads with nothing moved run no command (non-racy clock). The existing
   `test_the_branch_token_costs_one_git_command_per_adapter_and_none_after` is renamed and re-counted: the first
   token now reads the state, so it costs 1 + 3, then nothing.
4. **Racy window**: with `now` just after a watched file's mtime, the second read runs git again. With `now` past the
   window, it doesn't.
5. **Reftable availability**: reftable needs git ≥ 2.45. The cases skip with that reason when the installed git can't
   `init --ref-format=reftable`, but fail instead of skipping when `CI` is set, so CI can't lose the coverage quietly.

In `packages/troupe/tests/test_event_service.py` (lineage), parametrised over both adapters where it applies:

6. **N events, fixed cost**: record 5 and then 50 events through commands with the actor given, with a git adapter
   whose clock is past the window. Assert the same `commands_run` delta. With the files adapter, assert that no
   command runs (no adapter commands, and no subprocess at all, by patching the platform's process runner to fail).
7. **Lineage after operations, in a session**: record, commit / switch / merge / reset, record. The second event names
   the new branch and HEAD. This runs with the real clock and default window.
8. **Lineage across processes**: a child Python process (a helper like `perform_child.py`) holds one `EventStore`
   and records an event per line it reads on stdin. Between lines, the test process commits, switches, merges and
   resets. Every event's lineage matches `git rev-parse HEAD` and `git symbolic-ref --short HEAD` taken at that step.
   The child is fed with bounded waits, so it never hangs the suite.

## Risks / Trade-offs

- [A filesystem whose clock is far behind the wall clock, such as a network share, would make files look old, so
  the racy rule wouldn't fire] → Only a same-tick race could still slip through, as it can for git's own index. The
  window and rule are named, so they're easy to change.
- [For the racy window after a git operation, reads and writes run git on every call] → 0.1 s on fine-timestamp file
  systems. Only coarse ones (FAT, HFS+) pay 2 s. Recording a long run's events, the common case, is cached.
- [git might change which files a ref update touches] → The differential test runs against the installed git on
  every OS in CI. A future git that moves refs elsewhere fails it loudly, and doesn't leave lineage quietly wrong.
- [The wider token makes the text store rebuild more often on reftable or reflogs-off repositories] → Only when
  something actually moved, which is when it should have rebuilt all along.

## Migration Plan

None. Nothing persisted changes. Rolling back restores per-event git commands and today's token.
