# Tasks

## 1. Platform: copy-on-write clones (design D3)

- [x] 1.1 Add `troupe/platform/clones.py` (new code; it replaces no existing copy path, so there's no old behaviour to
  test against first) with `clone_file(src, dst) -> CloneMechanism`. It uses `clonefile` through `ctypes`
  on macOS, `FICLONE` after an exclusive create on Linux, and `_winapi.CopyFile2` with `COPY_FILE_FAIL_IF_EXISTS` on
  Windows. It falls back to an exclusive-create `copy` on the "unsupported" errnos, and recreates a symbolic link as
  a link. Verify with `packages/troupe/tests/test_platform_clones.py`, which covers:
  - the same bytes and mode;
  - an executable bit kept on POSIX;
  - a symbolic link copied as a link, whose target isn't read;
  - a destination that already exists, which fails and stays unchanged;
  - a failed clone, which leaves no destination;
  - the fallback, driven by a fake ioctl or `clonefile` that raises `EOPNOTSUPP`, reporting `copy`;
  - `clonefile` reported on macOS CI (APFS), `copy` on Linux CI (ext4), and `copyfile2` on Windows CI.

  Each test's name states only what its body checks.
- [x] 1.2 Add the clone section to `contributing/platform.md`: the mechanisms per OS, the fallback errnos, and that
  Windows can't report a block clone. Verify with `test_platform_docs.py`.

## 2. VCS port: the worktree capability and shared-state snapshots (design D4, D5, D10)

- [x] 2.1 Extend the `Vcs` protocol in `core/vcs.py` with:
  - `paths_differing_from_head`, `files_at_head`, `add_worktree`, `fill_worktree`, `capture`, `check_apply`, `apply`
    and `remove_worktree`;
  - `shared_state` and `SharedState.compare`;
  - their result types (`FillReport`, `Capture`, `Applicability`, `SharedChanges`).

  Add the `vcs.worktrees-unsupported` error with a details schema in `protocol/`. Verify that mypy --strict passes
  and that `test_errors.py` validates the new code's details.
- [x] 2.2 Make the files adapter refuse every worktree operation with `vcs.worktrees-unsupported`, naming the
  adapter, and return an empty shared state. Verify with tests in `packages/troupe-vcs-files/tests/`.
- [x] 2.3 Give the git adapter `add_worktree` and `remove_worktree` (`git worktree add --detach --no-checkout`, then
  `git worktree remove --force`, and `git worktree prune` when the directory is already gone). Verify that
  `git branch --list` and `git worktree list` are unchanged after a make and remove, and that removing a worktree
  deleted by hand succeeds.
- [x] 2.4 Give the git adapter `paths_differing_from_head`, `files_at_head` and `fill_worktree`: `read-tree HEAD`,
  then clone the matching files through an injected `clone_file`, then `checkout-index -a`, then verify with
  `update-index --refresh` and `diff-files`, checking out again once and then `workspace.not-at-head`. Verify with
  `test_git_worktrees.py`:
  - a dirty theatre's worktree matches HEAD exactly;
  - an untracked file in the theatre isn't in the worktree;
  - a file edited between the listing and the clone is checked out again, using an injected clone that edits the
    source first;
  - a sparse or absent path is checked out;
  - the reported mechanisms match what was used.
- [x] 2.5 Give the git adapter `capture`: `add -A`, then `write-tree`, then
  `diff --binary --no-renames --no-ext-diff --no-textconv --ignore-submodules` with `:(exclude).troupe`, streamed to
  a writer, with the counts and the left-out count. Verify these:
  - added, modified and deleted counts are right;
  - a binary file round-trips;
  - an actor's commit in the worktree is included from the base;
  - an ignored file is left out;
  - a `.troupe/` change is counted and left out;
  - an empty capture has no diff;
  - a person's `diff.renames=copies` and an external diff driver don't change the diff.
- [x] 2.6 Give the git adapter `check_apply` and `apply`: `git apply --check`, then `git apply`, unstaged, naming the
  files that fail. Verify these:
  - a two-file diff where one file conflicts changes neither file;
  - the index and HEAD are unchanged after an apply;
  - a CRLF round trip with `* text eol=crlf`, on Linux, macOS and Windows, written with `write_bytes`.
- [x] 2.7 Give the git adapter `shared_state`: refs from `for-each-ref` (including `refs/stash`), the hashes of the
  common `config` and `config.worktree`, and the hash and mode of each file in `--git-path hooks`, following
  `core.hooksPath`. Verify these:
  - a tag made between snapshots shows as added, and nothing else does;
  - a branch, a stash, a `git config` change and a new hook each show;
  - making and removing a worktree shows nothing.
- [x] 2.8 Add the worktree limits to `troupe_vcs_git/defaults.py`: `GIT_WORKTREE_TIMEOUT_SECONDS`,
  `GIT_WORKTREE_MAX_OUTPUT_BYTES` and `GIT_DIFF_MAX_BYTES`. Use them in 2.3 to 2.7, and document them in
  `contributing/platform.md`, beside the git adapter's other limits. Verify with a test that a worktree command past its announce time is announced, and that
  one past its timeout fails naming the command and the timeout, using a small injected timeout. The docs test
  should list the new defaults.

## 3. Config: the actor's `workspace` (design D9)

- [x] 3.1 Add `workspace` (`"worktree" | "theatre"`, optional) to `protocol/schemas/config/actor.schema.json`, and
  regenerate the pydantic models. Add `WORKSPACE = "worktree"` to `core/defaults.py`. Verify these:
  - `troupe config set actors.tester.workspace=theatre` is accepted;
  - `sandbox` is refused, naming the path and both accepted values;
  - the types-and-schemas agreement property test passes;
  - `scripts/check.py` regeneration check is clean.
- [x] 3.2 Document `workspace` in `docs/prompt-book/config-schema.md`. Verify with the docs tests.

## 4. Recording: run events and their schemas (design D7, D10)

- [x] 4.1 Extend `run-started.schema.json` with `workspace` (`worktree` with path, base, dirty and clones, or
  `theatre`). Extend `run-ended.schema.json` with optional `changes` (a diff reference and counts, `leftOut`, an
  optional `shared` holding refs, config and hooks, or `error` alone). Add `run-changes-accepted.schema.json` and
  `run-changes-discarded.schema.json`. Verify with `test_event_schemas.py`: real payloads validate, and
  contradictions don't (a diff with an error, `changes` on a `theatre` run, a null).
- [x] 4.2 Add `workspace` to `Run.Started`, and `changes` to `Run.Ended`. Add `accept_changes(diff)` and
  `discard_changes()` to the run aggregate, which record `Run.ChangesAccepted` and `Run.ChangesDiscarded`. Both are
  allowed only after the end, and only once, with `run.changes-settled` otherwise. Register the new topics in
  `TOPICS`. Verify with aggregate tests:
  - an accept before the end is refused;
  - a second settle is refused, naming the first;
  - an old run without `workspace` reads back as `theatre`, so earlier events still load (a start recorded with
    no `workspace`, exactly as runs before this change were).
- [x] 4.3 Derive the changes state (`pending`, `accepted`, `discarded`, `none`, `uncaptured`) in
  `runs/projections.py`, with `uncaptured` for a capture error and for an interrupted worktree run. Verify with
  projection tests covering each state.

## 5. Stage and perform (design D1, D2, D8)

- [ ] 5.1 Change the `Stage` port's `workspace` to take the run id and the actor's workspace kind, and return a
  `Workspace` (its kind, path, capture and settle). In the local stage, build the worktree from the VCS port under
  `.troupe/local/worktrees/<run-id>/`, and keep `admit` as it is. Verify with `test_local_stage.py`:
  - the admission and lineage are identical for `worktree` and `theatre`;
  - `theatre` returns the theatre's root.
- [ ] 5.2 In `perform`:
  - check the VCS's worktree capability and HEAD (`vcs.worktrees-unsupported`, `workspace.no-head`, each with a fix
    naming `actors.<name>.workspace=theatre`) after the existing checks;
  - make the worktree after the lease. On failure, remove the partial worktree and the lease, and record nothing;
  - send `workspace.uncommitted-unseen` for a dirty theatre, with the count and up to `UNCOMMITTED_NOTICE_PATHS`
    paths;
  - snapshot the shared state;
  - run with `cwd` and `ExpectedFiles` in the workspace;
  - after the host returns, snapshot again, compare, and send `workspace.shared-git-changed` (hooks first) when
    anything changed;
  - capture the diff into the artifact store, and record `changes` (with `shared`) in the end. A capture failure
    becomes `changes.error` and keeps the worktree.

  Verify with `test_perform.py`, one test per scenario in the `run-workspaces`, `runs` and `stages` deltas:
  - the actor sees HEAD, and the theatre is untouched;
  - two runs get two worktrees;
  - the dirty warning, and the clean case with no notice;
  - a refused perform leaves no worktree;
  - a make failure leaves nothing registered;
  - an effect check runs in the worktree;
  - a failed run still captures;
  - a branch, a hook and a config change are each reported;
  - a capture failure is recorded with the worktree kept;
  - `never-started` still records `changes`.
- [ ] 5.3 Make the rehearsal report the workspace and base, and make no worktree. Verify with a test in
  `test_perform.py`, and the CLI rehearsal scenario.
- [ ] 5.4 Add the notices `workspace.uncommitted-unseen`, `workspace.not-removed` and
  `workspace.shared-git-changed`, and the errors `workspace.no-head` and `workspace.not-at-head`, each with a details
  schema. List them in `contributing/runs.md`. Verify with `test_notices.py`, `test_errors.py` and the docs tests.
- [ ] 5.5 Update existing tests and fixtures that expect a run's files in the theatre: set `workspace: theatre`
  where in-place is what's being tested, and otherwise assert the worktree path. Verify that the full
  `uv run scripts/check.py` passes.

## 6. Diff, accept and discard in the core and the protocol (design D6)

- [ ] 6.1 Add the client schemas `diff-request/result`, `accept-request/result` and `discard-request/result`, with
  run, `reason` and `rehearse`, and no path, diff or workspace. Add `workspace` and `changes` to `run.schema.json`,
  with the conditional rules: `changes` only for a worktree, and `pending` needs a diff. Regenerate the message types.
  Verify with `test_client_schemas.py`:
  - a request holding `diff` is refused with `client.invalid-request`;
  - a summary with `theatre` and `changes` doesn't validate;
  - a null is refused.
- [ ] 6.2 Add `core/runs/changes.py` with the `diff` query and the `accept` and `discard` commands:
  - resolve the run by id or prefix;
  - refuse with `run.not-ended`, `run.no-changes`, `run.changes-uncaptured` or `run.changes-settled` as the spec
    says;
  - take the `.troupe/local/runs/<id>/settle` lock and reload the run;
  - for accept, check then apply, record `Run.ChangesAccepted`, then remove the worktree, with
    `workspace.not-removed` on failure;
  - for discard, remove the worktree, then record `Run.ChangesDiscarded`;
  - a rehearsal changes nothing.

  Add the errors `run.not-ended`, `run.no-changes`, `run.changes-uncaptured`, `run.changes-conflict` and
  `run.changes-settled`, with details schemas. Verify with `test_run_changes.py`, one test per scenario:
  - a clean accept (unstaged, worktree gone);
  - a conflict, where nothing changes and the worktree is kept;
  - accept after discard;
  - two concurrent accepts, where exactly one applies, run as two processes;
  - discarding an interrupted run;
  - the lineage of an accept (person, `cli`, the reason, no stage);
  - the diff query returns the artifact byte for byte;
  - a missing artifact in another clone.
- [ ] 6.3 Route the three calls through `core/client/dispatch.py`. Verify with `test_client_dispatch.py`.

## 7. CLI and docs (cli delta)

- [ ] 7.1 Add `troupe diff <run> [--json]`, `troupe accept <run> [--reason] [--rehearse]` and
  `troupe discard <run> [--reason] [--rehearse]`. Give `discard` help that says it removes files, not git state.
  Show the workspace line on `perform` and the settle hint at a worktree run's end. Verify with `test_cli_runs.py`:
  - the diff is byte-exact on standard output, and `git apply --check` accepts it at the base;
  - `--json` validates;
  - `accept --rehearse` exits with the "would change" code;
  - a conflict's standard error names the files, the reference, the worktree and `troupe diff`;
  - the end-of-run hint;
  - the usage-error shapes for the new commands, through the existing property test.
- [ ] 7.2 Document `diff`, `accept`, `discard` and `workspace` in these places:
  - `docs/prompt-book/cli.md`;
  - `docs/the-company/performances-and-runs.md`, including that a worktree contains nothing, that discard doesn't
    undo branches, tags, stashes, config, hooks or pushes, and that worktrees live under `.troupe/local/worktrees/`
    for tools that scan;
  - `docs/opening-night/first-performance.md`, where the walkthrough now accepts the run.

  Verify with `test_cli_docs.py` and the other docs tests, and by running the first-performance walkthrough's commands
  as written.

## 8. Integration

- [ ] 8.1 Run one end-to-end check on all three OSes in CI: a scripted actor with no `workspace` changes a file, adds
  one and creates a branch. Then `status` shows `pending` and the shared branch, `diff` shows the change, `accept`
  applies it unstaged, and a second run is discarded and leaves the theatre untouched. Verify that CI's `check` job
  passes on Linux, macOS and Windows.

## Workflow follow-up

- Open a follow-up issue, added to the troupe roadmap board, for the other ways to accept: staging the diff,
  committing it, and a three-way merge. They'd be configurable per stage or per run (owner, 2026-10-23).
- Correct #51's "discarding the worktree rolls the run back" wording when commenting after the merge: discard
  removes files, not shared git state.
- Run `/opsx:archive` on the branch before merging. After the merge, comment on #51 with the PR and the archived
  change, close it, and check that its card says Done.
