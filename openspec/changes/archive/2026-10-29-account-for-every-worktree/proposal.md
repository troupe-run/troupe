# Proposal

## Why

A run's start (`Run.Started`) is recorded when its runner's `init` arrives, but `perform` makes a worktree run's
worktree well before that. So when `perform` is killed, or fails, between making the worktree and recording the start,
the worktree is left in `.troupe/local/worktrees/<run id>` and no event names it: `troupe status` doesn't show the run,
`troupe discard` can't name it, and only a hand-run `git worktree remove` clears it (troupe#154, found while building
#51 and noted in the worktree-stage design's Risks). Storing the direction artifact is one such failure: it runs after
the worktree is made.

The issue asks that every worktree troupe makes be accounted for: an event names it, or it is removed. It recommends
recording a worktree run's start before the runner starts, so "every run is its stream" stays true and an interrupted
run with a worktree shows as `interrupted`, its changes `uncaptured`, like any other.

## What Changes

- **A run's start is recorded before anything that can leave something behind** (design D1, D2). `perform` makes
  every check that can refuse, stores the direction artifact, then records the run's start, and only then makes the
  worktree and starts the runner. This holds for every run, in a worktree or in the theatre: one rule, not two. That's wider than the
  issue, which names worktree runs, and the owner chose it (2026-10-29).
- **The start no longer holds the reported runner.** The runner's name and version come from its `init`, which is
  already recorded as the run's first reported event (seq 0). A run summary's `runner.reported` is read from there
  (design D3).
- **A worktree run's start names its worktree before it exists**: its path, base commit, prefix and whether the
  theatre was dirty, all known before the worktree is made. The clone mechanisms, known only once it's filled, are
  recorded in a new event, `Run.WorktreeMade`, before the runner starts (design D4).
- **A failure after the start and before the runner starts ends the run** with outcome `could-not-start`, the
  failure as its error, and the runner `never-started`, as when a runner can't be started. `perform` returns that run
  as it does for any could-not-start run. A worktree that was made is kept, so `discard` removes it (design D5).
- **`discard` works on a run whose worktree was never made, or was half made**, as it does on an interrupted run:
  removing a worktree that's gone, or only registered, succeeds (design D6).
- Starts recorded before this change keep reading back: `runner_reported` and the start's `clones` stay readable as
  optional fields, and are no longer written (design D7).

Out of scope:

- **Letting `discard` or `status` take a worktree no event names** (the issue's second option). Once the start comes
  first, no such worktree is made by this version of troupe. Worktrees an older version left behind are cleared with
  the issue's workaround, `git worktree remove --force`, then `git worktree prune`.
- **Removing a worktree when its run couldn't start.** The worktree-stage design keeps a worktree until its changes
  are accepted or discarded; this change doesn't add a second reason to remove one.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runs`: "Init is recorded first" becomes "The run's start is recorded before its runner starts": the start comes
  before the workspace is made, the reported runner comes from the `init` event, and a failure between the start and
  the runner ends the run `could-not-start`. "What a run was asked to do is kept" moves the clone mechanisms out of
  the start.
- `run-workspaces`: the clone mechanisms are recorded once the worktree is made, not in the start. Discarding a run
  whose worktree was never made, or only partly made, succeeds. A run killed before its worktree was made, or before
  its runner sent `init`, is shown and can be discarded.
- `client-protocol`: a run summary's worktree workspace leaves out `clones` until the worktree is made.

## Impact

- Code: `troupe.core.runs.perform` (order of steps, the recorder's start, the pre-runner failure path),
  `troupe.core.runs.aggregate` (start without `runner_reported`, new `WorktreeMade` event and its ordering rules),
  `troupe.core.runs.projections` (reported runner from `init`, clones from `WorktreeMade`), `troupe.core.workspaces`
  (making a worktree split into finding what's dirty, then making and filling it).
- Protocol: `events/run-started.schema.json` (descriptions; `runner_reported` and `clones` documented as written only
  by older versions), a new `events/run-worktree-made.schema.json`, `client/run.schema.json` (summary workspace's
  `clones` optional), in both `protocol/schemas/` and the package's copy, and the generated models and
  `docs/prompt-book/events.md`.
- Tests: perform, the run aggregate, run queries, event payloads, run changes.
- No migration: pre-alpha. Rollback is reverting the change; events recorded meanwhile hold the start before the
  runner and a `Run.WorktreeMade`, which an older troupe doesn't know.
