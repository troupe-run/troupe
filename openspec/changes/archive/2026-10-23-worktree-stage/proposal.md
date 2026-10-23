# Proposal

## Why

Today an actor on the local stage works directly in the theatre, so whatever it writes lands among the person's own
files. Nothing records what changed, and nothing undoes it. The owner asked on #3 for a way to capture an actor's
changes during a run and roll them back easily, without Docker. #51 is that feature. It depends on `perform` (#36),
which has landed.

## What Changes

- **Each run on the local stage works in its own git worktree, by default.** The worktree is a detached checkout of
  the theatre's HEAD, at `.troupe/local/worktrees/<run-id>/`. Files that match HEAD in the theatre are cloned
  copy-on-write where the filesystem supports it (APFS on macOS, reflinks on Btrfs and XFS, block cloning on a
  Windows Dev Drive or ReFS). Every other file is checked out by git. Before the actor starts, the worktree is
  checked against HEAD.
- **The worktree starts from HEAD, never from uncommitted edits** (owner, 2026-10-23). When the theatre has
  uncommitted changes, perform warns with the notice `workspace.uncommitted-unseen`: the actor won't see those
  changes, and accepting may conflict with them. The run still goes ahead.
- **A new actor field, `workspace`:** `worktree` (the default) or `theatre`, which runs in place as before. Each run
  records which workspace it used. On a theatre whose VCS can't make a worktree (the plain-filesystem adapter), or
  that has no commit yet, a `worktree` run is refused, and the fix names `workspace: theatre`.
- **The run's changes are captured as a diff when it ends,** whatever its outcome. The diff is git's binary diff of
  the worktree against the base commit. It's stored in the artifact store and recorded by reference in the run's
  end, with counts of files added, modified and deleted. Changes under `.troupe/` are left out of the diff and
  counted, so an actor can't write troupe's events or config through an accept.
- **New commands: `troupe diff <run>`, `troupe accept <run>` and `troupe discard <run>`.**
  - `diff` shows the captured changes.
  - `accept` applies them to the theatre's working tree as unstaged changes, all or nothing. A diff that doesn't
    apply cleanly is refused with `run.changes-conflict`, and nothing changes. The refusal names the files, the
    diff's reference and the worktree.
  - `discard` removes the worktree.
  - Each one is recorded on the run's stream, with the person's lineage. `accept` and `discard` both take
    `--rehearse` and `--reason`. Accepting or discarding is final: after one, the other is refused.
- **The worktree is kept until the run is accepted or discarded,** so nothing an actor wrote is lost by default.
  That includes files git ignores, which the diff doesn't carry.
- **The effect check reads the run's workspace,** not the theatre.
- **`status` shows each run's workspace, and the state of its changes:** `pending`, `accepted`, `discarded` or
  `none`.
- **The platform seam gains a copy-on-write file clone,** falling back to a plain copy. It says which mechanism it
  used.
- **The VCS port gains worktree operations:** make a worktree at HEAD, capture its diff, apply a diff, and remove a
  worktree. The plain-filesystem adapter refuses each of them with `vcs.worktrees-unsupported`.
- The local stage still enforces nothing. A worktree contains nothing: the process can still write outside it or
  reach the network. Decision #3's option C is unchanged, and so is the `stage` lineage of every run.
- **Discarding removes files, not git state.** A worktree shares the theatre's `.git`. Branches, tags, stashes,
  config, hooks and pushes the actor makes there land in the real repository, and neither the diff nor `discard`
  covers them. The docs say so (design, Risks). troupe snapshots the refs, config and hooks before and after each
  worktree run, records what changed in the run's end, and warns with `workspace.shared-git-changed`. It names a
  changed hook first (owner, 2026-10-23). A push can't be detected, so it's only documented.

Out of scope, as #51 and #3 say:
- enforcement (the Docker stage, #65, or a later sandboxed local stage);
- in-memory filesystems and Python audit hooks;
- OverlayFS;
- other ways to accept, such as staging the diff, committing it, or a three-way merge that leaves conflict markers.
  The owner wants these as later options, configurable per stage or per run (2026-10-23);
- copying ignored files such as `.venv` or `node_modules` into the worktree;
- submodule contents.

## Capabilities

### New Capabilities
- `run-workspaces`: Where a run works, and what happens to what it changed. It covers the per-run worktree, its
  starting state and the dirty-theatre warning, capturing the diff, and accepting, discarding and showing a run's
  changes, with their states.

### Modified Capabilities
- `stages`: The local stage's workspace is the actor's `workspace` (a worktree by default), no longer always the
  theatre.
- `config`: An actor gains the optional `workspace` field.
- `runs`: A run's start records its workspace. Its end records the captured changes. Accepting and discarding are
  recorded on the run's stream. `status` shows the changes' state. The effect check reads the workspace.
- `vcs`: The port gains worktree operations. The git adapter implements them, and the plain-filesystem adapter
  refuses them.
- `platform`: A file can be cloned copy-on-write, with a plain copy as the fallback, and the clone reports its
  mechanism.
- `cli`: The new `troupe diff`, `troupe accept` and `troupe discard` commands. A perform rehearsal also shows the
  workspace.
- `client-protocol`: Requests and results for `diff`, `accept` and `discard`. A run summary carries its workspace and
  its changes.

## Impact

- Code:
  - `packages/troupe/src/troupe/core/`: `stages.py`, `runs/perform.py`, `runs/aggregate.py`, `runs/projections.py`,
    `runs/queries.py`, a new `runs/changes.py`, `vcs.py`, `notices.py`, `defaults.py`, `client/messages.py`,
    `cli/`, and `troupe/platform/` (a new `clones.py`);
  - `packages/troupe-stage-local/`, `packages/troupe-vcs-git/` and `packages/troupe-vcs-files/`.
- Protocol: `protocol/schemas/config/actor.schema.json`, the run's started and ended event schemas, two new event
  schemas (changes accepted and discarded), `client/run.schema.json`, and new client request and result schemas for
  `diff`, `accept` and `discard`. The pydantic models are regenerated.
- Docs: `docs/prompt-book/cli.md`, `docs/the-company/performances-and-runs.md`,
  `docs/opening-night/first-performance.md`, `contributing/runs.md` and `contributing/platform.md`.
- Behaviour change for existing users: an actor without `workspace` now runs in a worktree, and its changes reach the
  theatre only through `troupe accept`. The fix is `workspace: theatre`. Pre-alpha, so there's no migration.
