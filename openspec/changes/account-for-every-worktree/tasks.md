# Tasks

Each commit runs `uv run scripts/check.py` first. Tests named here go in `packages/troupe/tests/` unless a path says
otherwise; each test's name states what its body checks.

## 1. The run's events: a start without the reported runner, and Run.WorktreeMade

- [x] 1.1 In `troupe.core.runs.aggregate`, add `Run.WorktreeMade` (`clones`) and its `worktree_made` method, refused
      with `run.out-of-sequence` unless the start's workspace is a worktree and no WorktreeMade, run event or end is
      recorded yet (design D4); add its topic to `TOPICS`, and update the module docstring for the start's new timing
      and the new event. Keep `runner_reported` as an optional `__init__` parameter for old starts (D7). Verify with
      new tests in `test_run_aggregate.py`: WorktreeMade after the start is recorded; refused for a theatre run,
      twice, after a report and after the end; an old start holding `runner_reported` replays.
- [x] 1.2 Add `events/run-worktree-made.schema.json` and update `events/run-started.schema.json` (description of when
      it's recorded; `runner_reported` and the worktree workspace's `clones` optional and described as written only by
      older versions), in `protocol/schemas/` and the package's copy, through `scripts/package_schemas.py` as the
      other schemas are. Regenerate the models (`scripts/generate_models.py`) and `docs/prompt-book/events.md`
      (`scripts/docs_reference.py`). Verify with `test_event_payloads.py`: a worktree run's segment lines, including
      WorktreeMade, validate by topic, and an old-shape start (with `runner_reported` and `clones`) still validates.

## 2. Reading runs back: the reported runner from init, the clones from WorktreeMade

- [x] 2.1 In `troupe.core.runs.projections`, take `runner.reported` from the `Run.Reported` with seq 0 when it's an
      `init`, whether or not the log is kept, preferring an old start's `runner_reported` (D3, D7); and add `clones`
      to a worktree workspace from `Run.WorktreeMade`, preferring an old start's own `clones`. Verify with
      `test_run_queries.py`: a run with an init reports its runner; one ended before init has no `runner.reported`;
      a worktree run started but not yet made has no `clones`; an old start's runner and clones read back.
- [x] 2.2 In `client/run.schema.json` (both copies), give the summary its own worktree workspace with `clones`
      optional, and regenerate the models. Verify with the client-protocol schema tests: a summary of a worktree not
      yet made validates, and the existing "changes that contradict the workspace" cases still don't.

## 3. Perform records the start before anything can be left behind

- [x] 3.1 Split `make_worktree` in `troupe.core.workspaces` into finding what differs from HEAD (announcing
      `workspace.uncommitted-unseen`, writing nothing) and adding and filling the worktree (removing what it made on
      any failure, as now) (D2). Verify with the existing `test_run_workspaces.py` dirty, clean and fill tests passing
      unchanged in what they check.
- [x] 3.2 Reorder `perform` as design D2 lists it: direction artifact, then what's dirty, then `Run.Started` recorded
      by the person's command, then `m.Started`, then the worktree, `Run.WorktreeMade` and the shared-state snapshot,
      then the run host. Remove `_Recorder`'s lazy start and its `_start(None)` fallback in `_end`, and update the
      module docstring. Verify with tests: a run's stream is start, (for a worktree) WorktreeMade, then the run events
      and its end; a run whose runner can't start still holds its start and end; a failing direction store records
      nothing and makes no worktree (in `test_perform.py`); a theatre run records its start before its runner's first
      event; and a real worktree run's segment lines, `Run.WorktreeMade` included, validate by topic (in
      `test_event_payloads.py`: 1.2 could only check hand-built events until perform recorded the event).
- [x] 3.3 Rename and update `test_run_workspaces.py`'s `test_the_runs_start_records_its_workspace_with_base_path_and_clones`
      so its name and body say the start holds base, path and dirty, and WorktreeMade holds the clones; the test for
      the start's runner when init arrives (in `test_perform.py` or `test_run_aggregate.py`) now checks the summary's
      `runner.reported`. Verify by running both files.

## 4. A failure before the runner starts ends the run

- [x] 4.1 In `perform`, end the run when making the worktree, recording WorktreeMade or reading the shared state
      fails after the start: outcome `could-not-start`, ending `never-started`, the error, the limits in effect, no
      changes; then raise the original error, or `run.recording-failed` with both errors when the end can't be
      recorded (D5). Reuse the run host's never-started outcome (`runners.host.not_started`, made public for it)
      rather than building the outcome by hand. Verify with tests: `test_a_worktree_that_fails_to_fill_records_nothing_and_leaves_no_worktree`
      becomes one that checks perform fails with git's error, no worktree is left, and the stream holds start and a
      `could-not-start` end with that error; a failing shared-state read leaves the worktree, records WorktreeMade and
      the end, and the run's changes are `uncaptured`; a failing end raises `run.recording-failed` and the run reads
      `interrupted`.
- [x] 4.2 Verify that discarding a run that ended `could-not-start` with its worktree made removes the worktree and
      records the discard, with a test in `test_run_changes.py`.

## 5. A killed perform leaves a run that names its worktree

- [ ] 5.1 Let `perform_child.py` stop at a named point for tests that kill it: after the start is recorded and before
      the worktree is begun, inside `add_worktree` once git has made its entry, and after the worktree is made and
      before the runner sends `init` (for example by printing a marker on the `Started` update and then blocking in a
      wrapped VCS or a runner that waits before its init). Verify by running it by hand to each point.
- [ ] 5.2 Add one test per point in `test_run_workspaces.py` (run-workspaces, "Every worktree troupe makes is named by
      an event"): kill the child, then `status` shows the run `interrupted` with changes `uncaptured` and the worktree's
      path, and `discard` succeeds, records the discard, and leaves no directory and no registration in
      `git worktree list --porcelain`. Verify on macOS locally and on all three OSes in CI.
- [ ] 5.3 Check whether a kill inside `git worktree add` can leave `.git/worktrees/<id>/locked` behind with the
      directory gone or partial, so `git worktree prune` skips it (D6). If it can, make the git adapter's
      `remove_worktree` unlock the entry first, with a test in `packages/troupe-vcs-git/tests/test_git_worktrees.py`
      that removes a locked, partly made worktree and leaves no registration. Record what was found in design D6
      either way.

## 6. Docs

- [ ] 6.1 In `docs/the-company/performances-and-runs.md`, say under "A run's state" that a run is in `status` from
      the moment `perform` records its start, before its runner starts, so an interrupted run's worktree is always
      named, and `troupe discard <run>` removes it; and that a run whose worktree couldn't be made ends
      `could-not-start`. Verify the docs build (`uv run scripts/check.py`'s docs step) and the text matches the specs.
- [ ] 6.2 Update the archived worktree-stage risk's follow-up pointer only if the docs or specs cite it as open:
      grep `openspec/specs` and `docs` for "init arrives" and "before its runner's init", and fix any text that still
      says the start waits for `init`. Verify the grep finds none.

## 7. Integration

- [ ] 7.1 Run `uv run scripts/check.py` in full and `openspec validate account-for-every-worktree --strict`, and show
      the results; push and confirm every CI job passes on Linux, macOS and Windows.

## Workflow follow-up

- Open the pull request with `Closes #154`, and set nothing else on the card: it's already In Progress.
- Act on Claude's review of the last push by tier, as `openspec/config.yaml` says, before archiving.
- `/opsx:archive` on the branch, then queue the merge with `gh pr merge <n>`.
- After the merge: comment on #154 with the pull request and the archived change, check #154 is closed and its card
  on the troupe roadmap says Done.
