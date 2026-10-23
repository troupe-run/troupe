# Design

## Context

See proposal.md for why. The owner's decisions on #141 (2026-10-23) are: recognise the file, leave git's index alone
for now (#156), and keep a copy of whatever the file holds before replacing it.

What exists:

- **Events never conflict in git.** Each session appends to its own segment (event-store spec, "Two branches never
  touch the same file"), so a merge brings in both branches' `Config.Changed` events whole. `read(store)` folds them
  into the merged config, or into conflicts when the two lines' net changes clash (config spec, "A merge combines
  each line's net change").
- **The projection is rendered, never merged.** `projection.render(config)` gives the bytes of every file, sorted
  so they depend only on what config holds. `projection.plan` compares them with the disk. A file can be replaced
  when its hash is in `recorded` (every hash a `Config.Changed` named for that path, on any line of history) or in
  this clone's `written.jsonl`. Otherwise it's refused, with a markers-specific message (`CONFLICTED`) when the file
  holds git's markers.
- **`--force` keeps a copy** in the artifact store before replacing, and reports the hash as `kept`.
- **The VCS port is read-only for the theatre.** The git adapter writes an index only inside a run's own worktree.
  `EventStore.vcs` is the adapter every config command already has.
- **`.troupe/.gitattributes` holds `actors/** -text`,** so a blob's bytes are the file's bytes on every OS.

Observed with git 2.56 in a scratch repository: a content conflict leaves stages 1, 2 and 3 in `git ls-files -u`.
A modify/delete conflict leaves stages 1 and 3 and puts the surviving side in the working tree. A clean merge leaves
stage 0. After the merge is committed, `git merge-file` on the base and both parents, and `git merge-tree
--write-tree` on the parents, each reproduce HEAD's blob byte for byte.

## Goals / Non-Goals

**Goals:**
- A merge of two branches' config needs no step on a projection file apart from `git add`, until #156 removes that
  one too.
- Nothing a person wrote is lost. A recognised file's bytes are kept, and a side troupe didn't write is still
  refused.
- The rewritten file is what the merged config says, worked out from both lines' events, not either side's text.
- Every behaviour that works today still works: a hand edit is refused, an older version is rewritten, and a clean
  merge that already matches config is left alone.

**Non-Goals:**
- Changing git's index, or committing (#156).
- Recognising merges older than HEAD, or octopus merges.
- Any change to the event format or to how config merges.

## Decisions

### D1. Recognise the merge from the VCS, not from the file's text

troupe asks the VCS which sides the file came from, and checks each side's hash against what it recorded. The file's
content is never read for its meaning. Markers are only used to choose the wording of a refusal, as they are today.

Alternatives, from #141:
- `merge=binary` in `.troupe/.gitattributes`. It needs no registration, but it turns every path both branches
  changed into a conflict, including the clean merges that work today.
- A custom merge driver. Every clone has to register it, and a clone that hasn't still gets markers, so this
  recognition would be needed anyway.
- Documenting the manual steps. That's today's interim, and it doesn't meet the done-when.

### D2. The port's query: merge sides under a directory

```python
@dataclass(frozen=True)
class MergeSides:
    kind: Literal["conflicted", "clean"]
    sides: tuple[bytes | None, ...]   # ours, theirs (or each parent); None: that side has no file
    merged: bytes | None              # clean: the bytes git merged (index stage 0, or HEAD's blob)

def merge_sides_under(self, directory: str) -> Mapping[str, MergeSides]: ...
```

It's shaped like `committed_under`: theatre-relative paths with `/` separators, and the config directories asked for
once per plan. The files adapter returns `{}`. Each side comes back as bytes, not a hash, so core keeps its one
definition of a file's hash (`file_hash`, SHA-256). git's blob ids are SHA-1, or SHA-256 in a SHA-256 repository,
and are never compared with troupe's.

The base isn't returned. Whether a file is safe to replace depends only on the sides it came from: if each of them
is troupe's, nothing in the merge was written by a person.

### D3. How the git adapter finds the sides

1. **Conflicted.** `git ls-files -u -z -- <dir>` lists the unmerged paths and their stage blobs. Stages 2 and 3 are
   read with one `git cat-file --batch`, and a stage that isn't listed is `None`. This covers anything that leaves
   unmerged entries: a merge, rebase, cherry-pick, revert or `stash pop`.
2. **Clean.** Only when there's a merge to look at: `MERGE_HEAD` exists (the parents are `HEAD` and `MERGE_HEAD`,
   and `merged` is the index's stage-0 blob), or `git rev-parse HEAD^@` gives exactly two parents (the parents are
   those two, and `merged` is HEAD's blob). The only candidates are paths under the directory whose merged blob
   differs from every parent's. A path equal to one side is already a version troupe recorded, and needs nothing
   new.
3. **Reproduce the clean merge.** `git merge-tree --write-tree -z <ours> <theirs>` merges the two parents again,
   with the same strategy (ort) and the person's merge settings, and writes the result as a tree without touching
   the working tree, the index or any ref. A candidate is reported only if merge-tree doesn't list it as
   conflicted, and its blob in the resulting tree is exactly `merged`. A merge edited before it was committed (an
   "evil merge"), or made with options merge-tree didn't get (`-X`, another strategy), won't reproduce, so it's left
   out and refused as today.

   This was first designed around `git merge-file` on the base and both sides, but that changed during apply.
   Matching ort needs `merge-file --diff-algorithm`, which arrived in git 2.44, and Apple's bundled git is older.
   It also needed a single merge base. merge-tree needs git 2.38, and handles several merge bases the way the
   merge itself did. merge-tree only writes unreachable objects to the object store, which `git gc` removes.

Every call runs through the adapter's bounded `git()` and its timeout, like every other git call. When nothing is
unmerged and there's no merge, the query costs one `ls-files`, one `rev-parse --git-path` and one `rev-parse HEAD^@`.

### D4. What counts as troupe's in `plan`

`plan` gains `merges: Mapping[str, MergeSides]` and `resolve: frozenset[str]`, the paths this command may rewrite
from a merge (D7). For each path where the disk and the rendered bytes differ, in this order:

1. Its hash is vouched for (recorded, or in `written.jsonl`): replaced as now, with no copy and no new notice. This is
   still what happens after `git checkout --ours`.
2. It's in `merges`, and every side that isn't `None` is vouched for:
   - `conflicted`: replaced whatever the working file holds (owner: keep a copy, D5). If the file is missing, it's
     written, as now.
   - `clean`: replaced only when the working file is exactly `merged`. A file edited after git merged it goes on to
     step 4.

   If the path is in `resolve`, the action is `write` or `remove`, as the merged config says, with `keep=True`. Its
   reason is `git left it conflicted, from versions troupe wrote` or `git merged it from versions troupe wrote`. If
   it isn't, the path is refused with the reason `MERGED`. Its message says the file is a merge of versions troupe
   wrote, and that `troupe flush` rewrites it from the merged config, keeping a copy.

   Only an explicit command rewrites it (owner, 2026-10-23). The alternative was that any command using config
   rewrites it as it flushes first. That was turned down because a `perform` would then replace a file
   the person may be resolving in their editor. A copy would be kept, but the file would change under them without
   their asking.
3. `force`: as now.
4. Refused. A conflicted path whose sides aren't all troupe's is refused with the markers message. It names each side
   that isn't troupe's (`ours`, `theirs`), and the fix says to check out the side that is, or to use `--force`. Any
   other path gets today's refusal.

The merged config is the only source of the new bytes. When config conflicts, `sync_files` refuses as it does today
(`config.conflict`) and the file is left alone. The `config set` that resolves the conflict writes it from the
resolved config. So the file always says what the merge of the two histories says, never what either side's text
said. This is the owner's point about replaying the history, and a test checks it: the rewritten file equals
`render(merged config)` and differs from both sides.

### D5. Keeping the bytes, including on a finished staged write

`execute` keeps a copy when `action.forced or action.keep`, using the same artifact-store call as `--force`. One
path needs care. In `config set`, the changed file is staged, the event is recorded, and the staged write is then
*finished*. `plan` skips the target of a finished write, so a conflicted file would be moved over without a copy.
The `finish` action therefore carries `keep=True` when its target's current bytes are recognised under D4 step 2
(and in `resolve`), and `execute` keeps the target's bytes before moving the staged file into place. The check `config set` makes before
staging also passes `merges`, so a side that isn't troupe's stops it before anything is recorded.

### D6. The notice `config.merge-rewritten`

`{code: "config.merge-rewritten", path, details: {merge: "conflicted" | "clean", action: "write" | "remove",
kept: "<hash>"}}`. The fix says to `git add` the file and commit the merge, and that #156 will do the `git add`. It's
emitted by `Flushed.notices()` for each kept action, and by `config set` for each file its change wrote with a copy
kept. `FileAction.kept` already carries the hash in results, so the client protocol needs no change beyond the notice
schema. A rehearsal reports the action and its reason and emits no notice, as rehearsals do today.

It's a new code rather than `config.file-rewritten` with more details, because the person has something to do
(`git add`), and `file-rewritten`'s fix is "Nothing to do".

### D7. Where the merges are read

Wherever a plan is made: `sync_files` (the flush every config-using command runs first), `flush_files` and each of
the plans in `config_set`. Each reads `store.vcs.merge_sides_under(...)` for the config directories. Under the lock,
the plan made again re-reads them too, so nothing is decided from a stale view of the index. This repeats the
"plan again under the lock" rule `flush` already follows.

What each one passes as `resolve`:
- **`flush_files`:** every path in `merges`, and its rehearsal does the same.
- **`config_set`:** the paths its own change writes, those where `render(before)` and `render(after)` differ.
  When config has conflicts, it passes every merged path instead. A change is recorded only if it resolves every
  conflict (`refuse_unrecordable`), and until one does, `troupe flush` refuses. Without this, a merged file the
  resolving change doesn't touch would deadlock: `config set` would refuse it, naming `flush`, and `flush` would
  refuse the conflict. The merge property test found this during apply, and the owner chose this fix over leaving
  the file for a `troupe flush` afterwards (2026-10-23). It works out its entries before its first plan, and passes
  the same set to that plan, the check before staging, the finishing plan and its rehearsal. With no conflict, a
  recognised file the change doesn't touch is refused, and nothing is recorded.
- **`sync_files`:** none. So `perform` and every other command that uses config refuse a recognised file, and the refusal
  names `troupe flush`.

## Risks / Trade-offs

- **The working file of a conflicted path is replaced whatever it holds.** → Only on an explicit `troupe flush` or
  the `config set` that writes it (D7), never as a side effect of another command. Its bytes are always kept, and the
  notice names the hash. This is the owner's choice over recomputing git's markers.
- **A clean merge made with non-default merge options won't reproduce.** → It's refused, as it is today, and the
  refusal's fix still works. This errs toward refusing, never toward replacing.
- **A few git calls are added to every command that uses config.** → One `ls-files` and one `rev-parse` when there's
  no merge. If timing shows it matters, cache on `branch_token`, which changes when HEAD or the index changes
  (cache-vcs-state D5). Measure it before adding the cache.
- **`git add` is still manual** until #156. → The notice says so every time it rewrites a file. git's own status
  shows the file as unmerged too.
- **A file someone edited in a committed merge (an evil merge) whose sides are troupe's** won't reproduce, so it's
  refused, not replaced. That's the safe direction.

## Migration Plan

None. No event, file or setting changes format. The interim refusal text and the docs' manual steps are replaced in
the same change.
