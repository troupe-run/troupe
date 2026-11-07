# Design: a run's notices are kept in its history

See [proposal.md](proposal.md) for why. Behaviour is in the deltas to [runs](specs/runs/spec.md),
[client-protocol](specs/client-protocol/spec.md) and [cli](specs/cli/spec.md).

## Context

- **Where a run's notices come from.** In `perform` (`core/runs/perform.py`), after the run id is minted, notices
  arrive through two callbacks that both end in `send(_notice(notice))`:
  - `announce`, passed to the workspace operations: `plan_worktree` (raises `workspace.uncommitted-unseen`, and
    `workspace.waiting`), `make_worktree`, `snapshot`, and `_changes`/`capture` (`workspace.shared-git-changed`,
    `workspace.waiting`). `plan_worktree` runs **before** `recorder.start()`, so its notices come before the run's
    start is recorded.
  - `on_announce`, passed to `run_actor`: `run.silent` (the watchdog), `run.retrying` (after `on_event` for the
    `retry` event), `run.scratch-not-removed` (in `run_actor`'s `finally`, after the runner ended), and, with PR #317,
    `run.estimate-dropped` (while handling the result, before `on_event` for it).

  Before the id is minted, `sync_files` raises `config.*` notices. After the end, nothing in `perform` raises one.
- **Threads.** `workspace.waiting` is raised from a `threading.Timer` thread (`workspaces.announced`), while the
  workspace operation runs in an `asyncio.to_thread` worker. The run host's notices are raised synchronously on the
  event loop. `on_event` is async, and the host awaits it before reading the next line.
- **The recorder.** `_Recorder` records the start and `Run.WorktreeMade` through the person's command, and each
  `Run.Reported` and the end through the agent's, each in `asyncio.to_thread`. The `Run` aggregate is held in memory
  and appended to in order; a failed write sets `stale`, and the end reloads the aggregate. A failed event sets
  `failure = (seq, error)` and cancels the run; later events are dropped.
- **Reading back.** `RunView.apply` (`projections.py`) folds a run's recordings; with `keep_log` it builds `log`, a
  list of `LoggedEvent`. `logs` returns `LogsResult(run, events=view.log, notices)`, and following sends
  `view.log[sent:]` after each wake. `troupe logs` prints events on standard output and the result's notices, which
  `logs` derives, on standard error.
- **Bounds that exist already.** `run.silent` is announced once per silence: `silence_announced` resets only when
  the next event arrives. `run.retrying` is one per `retry` event. `workspace.waiting` is at most one per operation,
  and a run has at most five. Every other run notice is raised at most once.

## Goals / Non-Goals

**Goals:**
- Every notice a run raises survives the run, in order with its events, whether or not anyone watched it live and
  whether or not the run recorded an end.
- One place decides what's recorded and in what order: the recorder.

**Non-Goals:**
- Changing which notices exist, what they say, or when they're raised (#327, "Out").
- Recording notices for runs recorded before this change. There are none to keep compatible (pre-1.0).
- Showing recorded notices live in `perform`'s own output twice: `perform` keeps its live notice updates only.

## Decisions

### D1. One `Run.Noticed` event per notice, in the run's stream

`Run` gains `notice(data)`, recording `Run.Noticed` with one field, `notice`: the notice as `notice.schema.json`
data. It's refused as `run.out-of-sequence` before the start (the aggregate can't exist then anyway) and after the
end. It doesn't touch `next_seq`, so the `seq` rule for run events is unchanged. The topic joins `TOPICS`, with its
payload schema `protocol/schemas/events/run-noticed.schema.json`, and `event-record.schema.json` selects it.

- *Rejected: a list of notices in `Run.Ended`.* An interrupted run, the case where the notices matter most, never
  records an end, so it would lose them all. The order among the events would also be lost.
- *Rejected: a stream of notices apart from the run's.* The run's stream is what `status` and `logs` already fold,
  and its order is the order things happened. A second stream would need its own ordering against the first.
- *Rejected: a `notice` kind of `Run.Reported`.* `Run.Reported` is the runner's events by `seq`, with the agent as
  actor. A notice is troupe's, and has no `seq`.

### D2. The run's notices are the ones `perform` raises from the id's minting to the end

After `perform` mints the run id, both callbacks (`announce` and `on_announce`) go to one function,
`recorder.notice`, which sends the notice live straight away and queues it for recording. Notices raised before
`recorder.start()` (planning the worktree) wait in the queue, which starts writing once the start is recorded, so
they're recorded straight after it.

The `config.*` notices `sync_files` raises come before the id, so they aren't the run's. The event store's notices
and those `status` and `logs` derive aren't raised by `perform` at all. `accept` and `discard` (`changes.py`) raise
`workspace.not-removed` and `workspace.waiting` after the run ended, and their results carry them; recording them
would mean allowing an event after a settled end. This is the boundary #327 draws ("raised during it"); if the owner
wants `accept` and `discard`'s notices kept too, that's an added requirement, and a later `Run.Noticed` after
settling, not a change to this design.

- *Rejected: record each notice where it's raised.* The workspace operations and the run host don't know about the
  event store, and shouldn't. Routing through the callbacks they already take keeps them unchanged.

### D3. One writer records the run's events and notices, in the order they arrive

The recorder gets a FIFO queue and one writer task that takes each entry (a run event or a notice) and records it
through `asyncio.to_thread`, one at a time. Entering the queue is synchronous and safe from any thread: from the
event loop it appends directly, and from another thread (the `workspace.waiting` timer) it goes through
`loop.call_soon_threadsafe`. `on_event` queues its event and awaits that entry's completion, so the host still
waits for each event to be recorded, as now, and the `LoggedEvent` update is still sent after it. `recorder.notice`
doesn't wait. `end` waits for the queue to empty, then records the end, so every notice raised before the host
returned is recorded before the end. `_could_not_start` does the same.

The order in the stream is the order the entries reached the queue. For the run host that's the order it raised
them, because it calls both callbacks from the event loop. A `workspace.waiting` from the timer thread is ordered by
when it reached the loop, which is only a few microseconds from when it fired.

- *Rejected: an `asyncio.Lock` around each write.* A synchronous callback can't await it, and it would have to
  spawn a task per notice, whose start order isn't the order the notices were raised.
- *Rejected: writing the notice in the callback, blocking.* The run host's callback runs on the event loop, and the
  store's fsyncs and git calls must stay off it.

### D4. A recorded notice has the person as its actor

Each `Run.Noticed` is recorded through the person's command (`via` `cli`), like the start and `Run.WorktreeMade`.
troupe raises the notice for the person running `perform`; the agent didn't say it, even when it's about the
runner (`run.estimate-dropped`). It shares the run's change id and cause like every other run event.

- *Rejected: the agent's command.* Lineage would claim the agent said something it didn't.

### D5. A notice that can't be recorded fails recording like a run event

If recording a notice fails, the recorder sets `failure` to the notice's code and the error, sets `stale`, and
cancels the run; nothing later in the queue is recorded. Every notice is still sent live. The end's `recording`
becomes `{"notice": <code>, "error": ...}` in place of `{"failedAt": <seq>, "error": ...}`: exactly one of the two,
naming whatever failed first. `run.recording-failed`'s details follow the same rule (`notice` or `failedAt`), and its
problem says "couldn't be recorded from the notice <code> on". `recording`'s schema in `run-ended.schema.json` and the
client summary becomes a `oneOf` of the two shapes.

- *Rejected: drop a notice that can't be recorded and carry on.* A store that can't write a notice won't write the
  next event either, and "any failure to record stops the run" is the rule the run's history depends on: a history
  with a silent gap reads as complete.
- *Rejected: keep `failedAt` required, set to the next `seq`.* After the runner's last event (the scratch notice)
  there is no next `seq`, so the number would name an event that never existed.

### D6. No bound on how many notices a run records

Every run notice is bounded by something already recorded or fixed (see Context): at most one per run event, plus
at most five `workspace.waiting` and a handful of once-only notices. A notice is a few hundred bytes. A rate limit or
summary would add a second rule for what's kept, and a dropped `run.retrying` is exactly the trace #327 wants. A notice
added later that could repeat without such a bound must say what bounds it; `contributing/runs.md`'s notice list
gains that rule.

- *Rejected: a cap per code, with a count of what was dropped.* It would need a named setting and a summary event,
  for repeats the existing raising rules already prevent.

### D7. Notices are masked before they're sent or recorded

`recorder.notice` passes each notice through the run's credential masker (the one the run host builds from the
runtime's value) before sending it or queuing it. The run host's notices are already built from masked lines, and
the workspace notices hold paths, so this changes nothing today; it keeps the masking rule ("in any error or
notice") true in the one place a notice is written.

### D8. Read back: the summary's `notices`, and the log as events and notices

`RunView` keeps `notices`, a list of `{at, notice}`, always (a run has few), and with `keep_log` adds a
`LoggedNotice` (`{kind: "run-notice", runId, at, notice}`) to `log` in stream order, beside the `LoggedEvent`s. The
summary carries `notices` when the list isn't empty (omit-nulls: absent, never empty). The `logs` result's `events`
becomes `log`, a list of either entry; following sends `view.log[sent:]` as now, so recorded notices go out as
updates of kind `run-notice`. `logs-update.schema.json`'s `oneOf` gains `loggedNotice`.

The kind is `run-notice`, not `notice`, because `notice` is already the kind of the updates `logs` sends itself
(`noticeUpdate`, such as `events.subscription-polling`), which aren't part of the run's history.

- *Rejected: keep `events` and add a separate `notices` list to the result.* The order between them would be lost
  on the wire, and the result already has a `notices` field for something else.
- *Rejected: keep the field name `events` for a list that holds notices too.* The name would claim less than it
  holds. The protocol is version 0, changed in place, with no old clients to keep working.

### D9. The CLI shows recorded notices as part of the run

`render_run` adds a `notices:` line followed by one line per notice, `    <at> <code>: <problem>`, when the summary
has any. `render_run_line` appends `, <n> notices` (or `1 notice`) when there are any. `troupe logs` prints a
`run-notice` entry as `       <at> notice <code>: <problem>`, the seq column blank, on standard output among the
event lines; `on_update` handles kind `run-notice` the same way. The derived notices stay on standard error through
`render_notice`.

### D10. PR #317 needs nothing from this change

`run.estimate-dropped` is raised through the run host's `notice`, so it reaches `on_announce` and is recorded,
before the result event it concerns. Whichever of the two merges second checks, on rebase, that a test performs a
run whose runner sends an estimate without a price and finds the notice in the run's stream, and that #317's spec
text doesn't contradict this one.

## Risks / Trade-offs

- [A recorded notice can hold a host path outside the theatre: `run.scratch-not-removed` names the scratch
  directory, under the platform's temporary directory, and git then shares that path with whoever pulls the
  history.] → It's what the person was told, and #327 rules out changing what notices say. The path names a
  temporary directory, not a theatre, so it addresses nothing in a hosted deployment. Recorded here so a later change
  can make that notice name the path relative to `RUN_SCRATCH_ROOT`.
- [A notice failing to record now cancels a run that would otherwise have gone on.] → The same is true of a run
  event, and a store that fails one write fails the next. The end says exactly what wasn't recorded.
- [The writer task adds a moving part to `perform`.] → `end` and `_could_not_start` both wait for the queue to
  empty, and a test raises notices from the timer thread and from the event loop together and checks the order and
  that none is lost.
- [The `logs` result's field is renamed.] → Pre-1.0 (no compatibility forms), and its readers are the CLI and the
  tests in this repository; task 5.3 searches the org's other repositories for any reader before it lands.

## Migration Plan

None. The protocol changes in place at version 0, and there are no recorded runs to keep readable.
