# Design

## Context

See proposal.md, Why. How `perform` (`troupe.core.runs.perform`) runs today, checked on 2026-10-29:

1. Refusals, with nothing written: identity, policy and stage, config and the actor, the runner's name, and for a
   worktree run `worktree_base` (`vcs.worktrees-unsupported`, `workspace.no-head`). A rehearsal returns here.
2. `sync_files`, then the run id is minted and the run's lease taken (`.troupe/local/runs/<id>/`).
3. `make_worktree`: `differing_from_head`, the `workspace.uncommitted-unseen` notice, `add_worktree`, `fill_worktree`.
   A failure inside it removes what was made and raises (BaseException included), so perform fails with nothing
   recorded. Then `snapshot` reads the shared state.
4. `m.Started` is sent, the direction is stored as an artifact, and the run host starts the runner.
5. `_Recorder` records `Run.Started` lazily, on the first run event (normally `init`, seq 0), with `runner_reported`
   from it. A run that never sent one gets its start from `_end`, just before its end.

So the window this change closes runs from `add_worktree` in step 3 to the runner's first event in step 5. The
`init` event is already recorded in full as `Run.Reported` seq 0 (`runner-protocol`: `init` carries
`runner: {name, version}`), so the reported runner is in the stream twice when `init` arrives.

The git adapter's `remove_worktree` already removes a worktree that's gone or was only partly made (`--force
--force`, then the directory, then `git worktree prune`), and `discard` already takes an interrupted run.

## Goals / Non-Goals

**Goals:**
- No sequence of kills or failures in `perform` leaves a worktree, whole or partial, that no event names.
- A run in the stream from the moment it can leave anything behind, so `status`, `logs --follow` and `discard` see it.

**Non-Goals:**
- Recovering worktrees an older troupe left behind (proposal, Out of scope).
- Changing what `Run.Started` means for lineage: its actor is still the person, via `cli`.

## Decisions

**D1. Every run records its start before its runner starts, in a worktree or in the theatre.** The issue's option
names worktree runs, but a theatre run killed before `init` is just as invisible today, and two orders for one event
means two code paths to test. With one order, `_Recorder` loses its lazy start, and its `_start(None)` fallback in
`_end`. This goes beyond #154, which names worktree runs; the owner chose it (2026-10-29). Rejected: only worktree
runs record early. It fixes the worktree, leaves the theatre run's gap, and keeps
the "start on first event" path for half the runs.

**D2. The order in perform.** After the refusals and `sync_files`, as today:

1. Mint the run id and take the lease (unchanged).
2. Store the direction as an artifact. It moves up from after the worktree, so its failure leaves nothing.
3. For a worktree run, find what differs from HEAD and send `workspace.uncommitted-unseen`: the first half of
   today's `make_worktree`, which writes nothing, so its failure still leaves nothing.
4. Record `Run.Started` (person, via `cli`), with the workspace's kind, path, prefix, base and dirty, and send
   `m.Started`.
5. For a worktree run, make and fill the worktree, record `Run.WorktreeMade` (D4), and snapshot the shared state.
6. Start the run host. Run events are recorded as they arrive, as today, by the agent via `runner`.

`make_worktree` splits in two in `troupe.core.workspaces`: one that finds what's dirty and says so, and one that adds
and fills, still removing what it made on any failure. Rejected: record the start after the worktree is made. That
narrows the window to one fsync but doesn't close it, and the issue asks that every worktree be accounted for.

**D3. The reported runner is read from the `init` event.** `Run.Started` stops recording `runner_reported`. The
projection's `RunView` takes the runner's name and version from the `Run.Reported` with seq 0 when its event is an
`init`, whether or not it keeps the log, and the summary's `runner.reported` comes from there. It's the event the
issue means by "an event of its own": no new topic is needed, since the `init` is already recorded whole. Rejected:
a new `Run.Initialised` event holding the name and version, which would record what `Run.Reported` already holds.

**D4. A new event, `Run.WorktreeMade`, holds the clone mechanisms.** They're known only once the worktree is filled,
which is after the start (D2). It's recorded by the person's command, via `cli`, with the same change id: troupe made
the worktree for the person, not the actor. The aggregate refuses it with `run.out-of-sequence` unless the run's
workspace is a worktree, its start is recorded, no run event or end is, and it isn't recorded already. The summary's
workspace is the start's workspace with `clones` added from it. It also says, in the stream, that the worktree was
made, which helps whoever reads an interrupted run's events. Rejected: the clones in the run's end, which an
interrupted run never records, and which is about how the run ended, not where it worked. Rejected: dropping the
clone mechanisms, which run-workspaces requires.

**D5. A failure between the start and the runner ends the run `could-not-start`, and perform still fails with
it.** This covers making the worktree, recording `Run.WorktreeMade`, and reading the shared state. The end's outcome
is the one the run host derives when a runner can't be started: outcome `could-not-start`, ending `never-started`,
the error, the limits in effect, no exit code, transcript or stderr. Its changes are left out, so a worktree run's
changes are `uncaptured`: the runner never ran, and troupe doesn't claim what it didn't check. Then perform raises
the original error, as it does today, so the person sees the same message and fix. If the end can't be recorded,
perform raises `run.recording-failed` with the original error and the end's, as `_recording_failed` already does,
and the run shows as `interrupted`. Rejected: returning the run as perform does when its runner can't start. It
would change what a person sees for a git failure, and its exit code, for no gain: the run is in `status` either way.

A Ctrl-C while the worktree is being made reaches the run host as today, through `session.cancel`, once the host
starts; nothing about cancelling changes here.

**D6. Discarding a run whose worktree is gone or half made needs no new code path.** `discard` already allows an
interrupted run and calls `remove_worktree`, which tolerates both. What's new is that such runs now exist in the
stream, so this change adds the tests. One case needs checking during apply: `git worktree add` locks the new entry
while it checks out (`.git/worktrees/<id>/locked`), and `git worktree prune` skips locked entries. If a kill can
leave the entry locked with no directory, `remove_worktree` unlocks it first (`git worktree unlock`), so the
registration goes too.

Found during apply (2026-10-29): it can. With the directory still there, `git worktree remove --force --force`
removes a locked entry. With the directory gone, `git worktree prune` leaves the locked entry registered, and
`git worktree unlock` works on it (exiting 128 for an entry that isn't locked or isn't registered). So the git
adapter's `remove_worktree` now unlocks first, allowing 128.

**D7. Starts recorded before this change keep reading back.** `run-started.schema.json` keeps `runner_reported` and
the worktree workspace's `clones` as optional fields, each described as recorded only by older versions. The
aggregate's `__init__` keeps the `runner_reported` parameter, so the library can replay old starts. The projection
prefers the start's own fields when they're there. The summary's `client/run.schema.json` gets its own worktree
workspace definition, with `clones` optional, rather than referring to the start's. Pre-alpha, so this is cheap
insurance for the theatres troupe is already dogfooded in, not a migration. Rejected: a strict new schema that
refuses old starts, which would make `status` fail on any theatre that ran a worktree run before this change.

## Risks / Trade-offs

- **A run that never got going is now in `status`.** A worktree that git couldn't make shows as a `could-not-start`
  run, where before nothing was recorded. → It's what the issue asks: the person sees it, and its error.
- **A start now precedes every git failure making the worktree, so such failures leave events.** → They're a run's
  events like any other, and they travel with the theatre's history. That's the point: they name the worktree.
- **Old troupe versions can't read `Run.WorktreeMade`.** → Pre-alpha, with no promise of reading newer events; the
  rollback note in the proposal says so.
- **The clone mechanisms are recorded by the person's command, while the worktree is made by troupe.** → Same as the
  start: `perform` acts for the person until the runner starts.

## Migration Plan

None: pre-alpha. Old starts still read (D7). Worktrees left by older versions are removed by hand, as the issue's
workaround says. Rollback is reverting the change.
