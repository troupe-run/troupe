# Design

## Context

See proposal.md for why. What exists today:

- `perform` (`core/runs/perform.py`) runs everything that can refuse first (identity, policy, the stage's admission,
  config, the runner's name). Then it mints the run id, takes the run's lease at `.troupe/local/runs/<id>/`, and calls
  the run host with `cwd=stage.workspace(theatre)`. The local stage's `workspace()` returns the theatre.
- The `Stage` port (`core/stages.py`) has `name`, `workspace(theatre)` and `admit(policy)`. The local stage
  (`troupe-stage-local`) refuses unless `allow_unenforced_local_stage` is true.
- The `Vcs` port (`core/vcs.py`) only reads: the branch, HEAD, the branch token, what is committed, and identities. The
  git adapter runs every git command through `troupe.core.commands.run_command` with `GIT_ENVIRONMENT`, a 10 s timeout
  and an announce after 1 s. The files adapter runs nothing.
- The run aggregate records `Run.Started`, `Run.Reported` and `Run.Ended`, and refuses anything after its end. Topics
  are import paths. Event payloads are checked against `protocol/schemas/events/*.schema.json`.
- `ExpectedFiles` (`core/runners/effects.py`) is built from paths joined to the theatre.
- `.troupe/local/` is ignored through the theatre's own `.troupe/.gitignore`, which troupe maintains.
- The decisions behind this design: option C on #3, #37 (neither transport is a sandbox), and the owner's answers of
  2026-10-23. Those answers were: start from HEAD and warn when the theatre is dirty, don't refuse; the worktree is the
  default, with a per-actor opt out; accept applies the diff unstaged for now, and other ways to accept come later.

## Goals / Non-Goals

**Goals:**
- A worktree run can never change the theatre's files. Only an explicit `accept` does that, and an accept either
  applies all of the diff or none of it.
- The diff is what git would show a developer, and applying it behaves as `git apply` does.
- Making the worktree costs little on a filesystem that can clone, and it is correct on every filesystem.
- One shape that a future Docker stage can reuse: make a workspace, run in it, capture it, then settle it.

**Non-Goals:**
- Containing the process. The worktree is a convenience, not a boundary. Lineage keeps saying `unenforced`.
- Reconciling with the theatre's uncommitted changes when the worktree is made, or when accepting (no three-way
  merge).
- Cleaning up old worktrees automatically. A retention setting can come later, once there's a reason to drop data.
- A JSON-RPC transport for the new VCS operations. The VCS port is direct today, as it already is.

## Decisions

### D1. The worktree is a registered, detached `git worktree`, under `.troupe/local/worktrees/<run-id>/`

`git worktree add --detach --no-checkout <path> <base>` registers it, and troupe then fills it in (D2). The actor gets
a real git repository: Claude Code and other agents can run `git status`, `git diff` and even `git commit` there.

Where it lives:
- **On the same volume as the theatre.** Copy-on-write clones only work within one volume, so a system temporary
  directory would often lose them.
- **Under `.troupe/local/`.** That directory is per clone and already ignored by troupe's own `.gitignore`, so the
  worktree never shows in the theatre's `git status`.
- **Under a dot-directory.** Most tools that walk a tree (pytest's default `norecursedirs`, ruff and ripgrep through
  `.gitignore`) skip it.
- **Keyed by run id.** Nothing else needs to find it.

Alternatives considered:
- A plain copy with a private `GIT_INDEX_FILE`. It leaves no git registration behind, but the actor can't use git.
- `../<repo>-run-<id>`, a sibling directory. It's outside the repo, but it's outside troupe's own state too: it could
  be on another volume, and it clutters the person's directories.
- OverlayFS. Linux only, and out of scope.

### D2. The starting state is HEAD exactly. Matching files are cloned, the rest are checked out, then verified

The owner chose HEAD over the working tree. Making the worktree:

1. `git status --porcelain=v2 -z --untracked-files=all` in the theatre gives the paths that differ from HEAD: staged,
   unstaged and untracked-not-ignored. A non-empty list sends `workspace.uncommitted-unseen`, with the count and up to
   a named number of paths, and the run's start records `dirty: true`.
2. `git worktree add --detach --no-checkout`, then `git read-tree HEAD` in the worktree. The index now holds HEAD, and
   no file has been written yet.
3. For each path in HEAD that isn't in the dirty list, and that the theatre has (sparse or skip-worktree paths can be
   absent), clone the theatre's file into the worktree through the platform seam (D3). Directories are made as
   needed.
4. `git checkout-index -a` without `-f`. It writes every file that isn't there yet: the dirty ones, the absent ones,
   and any whose clone failed.
5. Verify: `git update-index --refresh`, then `git diff-files --name-only -z`. Any path listed (a file the person
   edited between steps 1 and 3) is checked out again with `git checkout-index -f -- <paths>`, and the verification is
   repeated once. If anything still differs, the perform is refused with `workspace.not-at-head`, and the worktree is
   removed.

Why clone the theatre's file rather than check it out: for a file that matches HEAD, the theatre's bytes are already
exactly what checkout would write, with eol conversion and smudge filters applied. A clone shares their blocks. Step 5
is what makes this safe, so a racing edit can't leak into the run.

Alternatives considered:
- A plain `git worktree add`. It's correct, but it writes every file, so a large repo pays for a full checkout and
  gets no copy-on-write at all.
- Cloning the whole directory with `clonefile(2)` on a directory. That's macOS only, and it would bring along ignored
  and dirty files.

### D3. The platform seam's `clone_file(src, dst) -> CloneMechanism`

`troupe/platform/clones.py` keeps all the OS-specific code in one place:
- **macOS:** `clonefile(src, dst, CLONE_NOFOLLOW)` through `ctypes` from libSystem.
- **Linux:** open `dst` with `O_CREAT|O_EXCL`, then `fcntl.ioctl(dst_fd, FICLONE, src_fd)`.
- **Windows:** `_winapi.CopyFile2` with `COPY_FILE_FAIL_IF_EXISTS` and `COPY_FILE_COPY_SYMLINK`. That's the call
  `shutil.copy2` already makes on 3.12 and later, and Windows block-clones with it on ReFS and Dev Drive. Windows
  doesn't say whether it cloned, so the mechanism reported is `copyfile2`, never `clonefile`.

On `ENOTSUP`, `EOPNOTSUPP`, `EXDEV`, `EINVAL` or `ENOTTY`, a partly made destination is removed, and the file is
copied with `shutil.copy2(follow_symlinks=False)` after an exclusive create. The mechanism reported is then `copy`.
Symbolic links are recreated with `os.symlink(os.readlink(src))`. Any other error is raised as a `platform` error
naming both paths.

The run's start records the set of mechanisms used, for example `["clonefile"]`, or `["ficlone", "copy"]` when only
some files cloned. That's a fact about this run, not a promise about the filesystem.

Alternatives considered:
- `cp -c` or `cp --reflink=auto` as a subprocess. That's a process per file, and the flags differ by OS.
- `os.copy_file_range`. It doesn't reliably reflink across kernels, and it doesn't say whether it did.

### D4. The VCS port gains a `Worktrees` capability, separate from reading

There are new methods on the `Vcs` protocol, grouped and documented as the worktree capability:
- `theatre_prefix() -> str`
- `differing_from_head() -> tuple[str, ...]`
- `add_worktree(path, at) -> None`
- `fill_worktree(path, clone, skip) -> Filled` (D2, steps 2 to 5)
- `capture(path, base, leave_out, out) -> Captured`
- `check_apply(diff) -> Applicability`
- `apply(diff) -> tuple[str, ...]`
- `remove_worktree(path) -> None`
- `shared_state() -> SharedState` (D10)

A theatre can sit in a subdirectory of its repository (a monorepo), so these speak in repository-relative paths, and
`theatre_prefix` says where the theatre is. The run then works in `<worktree>/<prefix>`, and `.troupe/` is left out
as `<prefix>.troupe`. A diff passes through files rather than memory: `capture` writes it with `git diff --output`,
and `check_apply` and `apply` read it from a path. `clone` is the core's `clone_file`, which turns a platform failure
into `clone.failed`. A file whose clone fails is checked out instead.

The files adapter raises `vcs.worktrees-unsupported` from each one. Stages call these through the port and never
run git themselves, so the git knowledge stays in `troupe-vcs-git`.

Worktree commands get their own named defaults in `troupe_vcs_git/defaults.py`:
- `GIT_WORKTREE_TIMEOUT_SECONDS`, default 600 s, for `read-tree`, `checkout-index`, `status` and `diff` on large
  repos;
- `GIT_WORKTREE_MAX_OUTPUT_BYTES`, for `status -z` and `ls-tree -z` on large repos;
- `GIT_DIFF_MAX_BYTES`. The diff is streamed to the artifact store, never held in memory. Past this limit, the
  capture fails as in D7.

Each command still announces after `GIT_ANNOUNCE_AFTER_SECONDS`, which meets "never wait silently".

### D5. The diff: `git add -A` in the worktree, then `git diff --binary <base> <tree>`

Capture runs in the worktree:
1. `git add -A`. This stages everything git doesn't ignore, which includes any commits the actor made, because the
   index now reflects the files.
2. `git write-tree`, which gives the final tree.
3. `git diff --binary --no-renames --no-ext-diff --no-textconv --ignore-submodules <base> <tree> -- . ':(exclude).troupe'`
   streams the diff into the artifact store.
4. `git diff --name-status` with the same pathspec gives the counts. A second, `.troupe`-only `--name-only` gives the
   number of paths left out.

`--no-renames` keeps the diff dependent on neither the person's `diff.renames` config nor rename-detection
heuristics. `--no-ext-diff` and `--no-textconv` keep the person's diff drivers out of it. Accept runs `git apply`,
which reads with the same clean conversion and writes with the same smudge conversion as the theatre's checkout. I
checked this by hand with `eol=crlf`: the diff carries LF, and the theatre's file comes back CRLF. A test on all three
OSes covers it.

The worktree's index is left staged after capture. That's harmless, because the worktree only exists to be inspected,
accepted or discarded.

Alternatives considered:
- `git diff` against the working tree, without `add -A`. It misses untracked files.
- Comparing raw bytes with `--attr-source` and an empty tree. That bypasses filters, but then accept would write
  bytes the theatre's checkout wouldn't, which is wrong for LFS or `eol` files.

### D6. Accept is `git apply --check`, then `git apply`, unstaged, under the run's settle lock

`accept`:
1. Resolve the run. Refuse unless it's ended (`run.not-ended`), its changes are `pending` (otherwise
   `run.no-changes`, `run.changes-uncaptured` or `run.changes-settled`), and the diff's artifact is in this clone's
   store (otherwise the artifact store's own missing-artifact error, with a fix naming the worktree when it's
   present).
2. Take a lock, `.troupe/local/runs/<id>/settle`, using `directory_lock` and bounded by `LOCK_TIMEOUT_SECONDS`.
   Inside it, reload the run so the state is current. That covers two accepts racing.
3. `git apply --check`. On failure, raise `run.changes-conflict` with the files git names. Nothing has changed.
4. Unless rehearsing, `git apply`, which is atomic without `--reject`. Then record `Run.ChangesAccepted {diff}` in the
   person's lineage: via `cli`, no stage, with the reason. Then remove the worktree.

The event is recorded after the files are written. If recording fails, the files have changed with no event, and the
error says so and names the run: the state stays `pending`, and a second accept would then conflict. That order
loses no data. The other order, an event with no files changed, would claim something that didn't happen.

A worktree that fails to be removed after a recorded accept gives the notice `workspace.not-removed`, naming the path.
The accept still succeeds, and `discard` isn't needed. `status` shows the leftover path, and a second
`troupe discard` is refused as settled, so the fix is `git worktree remove <path>`.

`discard` takes the same lock, removes the worktree, then records `Run.ChangesDiscarded`. For a running run it's
refused with `run.not-ended`. An interrupted run's lease is free, so it can be discarded.

Other ways to accept (`--index`, a commit, or a three-way merge that leaves conflict markers) are later options,
configurable per stage or per run (owner, 2026-10-23). The request schema has no field for one, so adding one later
adds a field, and the default doesn't change.

### D7. Recording: three new places in the run's stream

- **`Run.Started`** gains `workspace`. For a worktree it's
  `{"kind":"worktree","path":".troupe/local/worktrees/<id>","base":"<sha>","dirty":bool,"clones":[...]}`. In place
  it's `{"kind":"theatre"}`. The path is theatre-relative, so a hosted deployment's events never hold a host path.
- **`Run.Ended`** gains `changes` for a worktree run. When captured it's
  `{"diff":"sha256:…","added":n,"modified":n,"deleted":n,"leftOut":n}`. It has no `diff` when nothing changed. When
  capture failed, it holds only `{"error": <error>}`.
- **Two new events**, `Run.ChangesAccepted {diff}` and `Run.ChangesDiscarded {}`, each with its own event schema. The
  aggregate allows them only after the end, and only one of them, once. A second is `run.changes-settled`.

The changes state (`pending`, `accepted`, `discarded`, `none`, `uncaptured`) is derived in the run projection, never
recorded. That fits "a run's state is derived".

`perform` captures after the run host returns and before `recorder.end`, so the end carries the changes. A capture
failure becomes `changes.error`. It never changes the run's outcome, because the actor's result is a separate fact.

### D8. Ordering in `perform`

`perform` now runs in this order:
1. All checks, as today.
2. `actor.workspace`. A worktree needs the VCS's worktree capability and a HEAD: `vcs.worktrees-unsupported` or
   `workspace.no-head`.
3. Rehearsal, which reports the workspace and base and returns.
4. Mint the run id, and take the lease.
5. Make the worktree. On failure, remove what was made, record nothing, and fail. The lease directory goes too, as it
   does today on an early failure.
6. Send `Started` and the workspace line.
7. Run the host with `cwd` set to the worktree, and `ExpectedFiles` joined to the worktree.
8. Capture, record the end, and return.

The `Stage` port's `workspace(theatre)` becomes `workspace(theatre, run_id, actor_workspace)`. It returns the
`Workspace`: its kind, its path, and a `capture()` and a `settle` handle. The local stage builds it from the VCS port.
A future Docker stage mounts the same worktree.

### D9. Names, all in one place

- **Notices** (in `core/notices.py`): `workspace.uncommitted-unseen`, `workspace.not-removed` and
  `workspace.shared-git-changed`.
- **Errors:**
  - `vcs.worktrees-unsupported`
  - `clone.failed`
  - `workspace.no-head`
  - `workspace.not-at-head`
  - `workspace.diff-too-large`
  - `run.not-ended`
  - `run.no-changes`
  - `run.changes-uncaptured`
  - `run.changes-conflict`
  - `run.changes-settled`

  Each one gets a details schema in `protocol/`.
- **Defaults:**
  - `WORKSPACE = "worktree"` (the default when `workspace` is absent);
  - `WORKTREES_DIR = "worktrees"`;
  - `UNCOMMITTED_NOTICE_PATHS = 20`;
  - the git limits in D4.

### D10. Shared git state is snapshotted before and after, and reported, never undone

A worktree shares the theatre's `.git`, so the diff can't see what an actor does to the repository itself. The owner
chose to detect and warn (2026-10-23). The VCS port gains `shared_state() -> SharedState`, and
`SharedState.compare(other) -> SharedChanges`.

What the git adapter snapshots:
- **Refs:** `git for-each-ref --format='%(refname) %(objectname)'`, which includes `refs/stash`. A worktree's own
  `HEAD` is a per-worktree ref that `for-each-ref` doesn't list, so making and removing worktrees isn't a change.
- **Config:** the SHA-256 of the common `config` file, and of `config.worktree` when present.
- **Hooks:** the SHA-256 and mode of each file in `git rev-parse --git-path hooks`, which follows `core.hooksPath`.
  When the hooks path is tracked (inside the theatre), changes to it also show in the diff, as they should.

The snapshot is taken after the worktree is made (step 5 of D8) and again after the runner ends, before capture. The
run's end records:

```json
"shared": {
  "refs":   [{"name": "...", "change": "added|changed|removed"}],
  "config": [...],
  "hooks":  [...]
}
```

The `shared` key is left out when nothing changed. The notice `workspace.shared-git-changed` names hooks first. Its
problem says these changes happened during the run (the person may have committed meanwhile) and that discard won't
undo them. Its fix names the git command to look at each kind.

The files adapter has no shared state, so its snapshot is empty. Alternatives considered:
- Refusing to settle until a hook change is acknowledged. That's heavier, and the owner didn't choose it.
- Separate clones per run instead of worktrees. They'd contain the refs, but they lose copy-on-write and the shared
  objects, and the actor could still reach the original.

## Risks / Trade-offs

- **The worktree contains nothing:** the actor can still `cd ..` into the theatre, write anywhere, or create a branch
  in the shared repo. → Lineage keeps recording `unenforced`, as before. The docs say plainly that a worktree catches
  mistakes, not malice. Option C on #3 still gates every local run.
- **A worktree shares the theatre's `.git` store, so discarding undoes no git state.** These all land in the person's
  real repository, outside the diff, and `troupe discard` doesn't undo them:
  - branches, tags and other refs;
  - stashes;
  - `git config`;
  - objects;
  - hooks. This is the sharpest: an actor that writes `.git/hooks/pre-commit` (found with
    `git rev-parse --git-common-dir`) plants code that runs in the person's own repository on their next commit;
  - `git push`, which reaches a remote with the person's credentials.

  This is a sharper form of "contains nothing", not a new boundary. The actor could equally write `../../.git/hooks`
  directly. Mitigations in this change:
  - the docs and the `discard` help say plainly that discard removes files, not git state;
  - #51's wording, "discarding rolls the run back", is corrected when the change lands.

  Containment needs the Docker stage (#65), a sandboxed local stage, or a separate clone per run. Detection is in this
  change (D10, owner 2026-10-23). A push can't be detected locally, so it's only documented.
- **Worktrees pile up under `.troupe/local/worktrees/`.** → `status` lists the pending ones. `discard` removes them.
  Automatic retention is a later setting, deliberately left out so nothing is dropped unasked.
- **Tools that ignore `.gitignore` and don't skip dot-directories may scan the worktrees.** → This is documented,
  with the path to exclude.
- **Copying is slow on large repos without copy-on-write.** → That costs no more than a plain `git worktree add`.
  Each step is announced, under a named timeout.
- **Accepting into a theatre that has changed since the base can conflict.** → It's refused all or nothing, naming
  the files and pointing at `troupe diff <run> | git apply --3way` as a manual route. Other ways to accept come
  later.
- **Windows can't report whether `CopyFile2` cloned.** → The mechanism is recorded as `copyfile2`, which is honest.
- **The diff's artifact is per clone,** so another clone that merges the run's events can't accept it. → It's
  refused with the artifact store's missing-artifact error. That's out of scope until artifacts travel.
- **Submodules aren't populated in the worktree.** → `--ignore-submodules` leaves their changes out. This is
  documented.

## Migration Plan

Pre-alpha, so there's no migration. Actors without `workspace` now run in a worktree. Existing tests and docs that
expect files to land in the theatre either set `workspace: theatre` or accept the run. Rollback is reverting the
change. Worktrees left behind are removed with `git worktree remove`, and `git worktree prune` clears their
registrations.
