# Proposal: a run's notices are kept in its history

Issue: troupe-run/troupe#327.

## Why

troupe raises notices while a run goes: a long silence (`run.silent`), an engine retrying (`run.retrying`), a slow
worktree operation (`workspace.waiting`), changes the run won't see (`workspace.uncommitted-unseen`), shared git state
that changed (`workspace.shared-git-changed`), a scratch directory left behind (`run.scratch-not-removed`), and, once
#292 (`estimated-cost`, PR #317) lands, an estimate dropped because troupe gave the runner no price
(`run.estimate-dropped`). Today they only go to whoever called `perform`, as live updates (`perform.py`,
`send(_notice(...))`). No run event keeps them, so after an unattended run, or from another terminal, nothing shows
that they happened. The owner chose to record every run notice, not to special-case the dropped estimate
(2026-11-07).

## What Changes

- **A new run event, `Run.Noticed`**, holds one notice as protocol data (`notice.schema.json`). It's recorded in the
  run's own stream, in the order troupe raised it among the run's other events. One event per notice, so the notices
  stay in order with the run's events, and a run that never records an end still keeps the ones it raised.
- **Which notices count as the run's**: every notice `perform` raises for the run, from when the run's id is minted
  until its end is recorded. That's the run host's (`run.*`) and the workspace operations' (`workspace.*`). Notices
  raised before the run's start is recorded (planning the worktree) are recorded straight after it. The config
  notices `perform` raises before it mints the id, the event store's notices, and the notices `status` and `logs`
  derive when they read a run (`run.interrupted`, `run.unfinished-elsewhere`) aren't the run's, and aren't recorded.
  Nor are the notices `accept` and `discard` raise after the run ended (`workspace.not-removed`, `workspace.waiting`
  while removing a worktree): they're separate commands, whose results already carry them. That boundary is an
  assumption the owner can widen (design D2).
- **No rate bound.** Every notice a run can raise is bounded already: `run.silent` once per silence (it resets on the
  next event), `run.retrying` once per `retry` event, which is itself recorded, `workspace.waiting` at most once per
  workspace operation, and the rest at most once per run. So a run records at most one notice per event, plus a few.
- **Live updates don't change.** `perform` still sends each notice as it's raised. Recording it doesn't delay it.
- **A notice that can't be recorded is a recording failure**, like a run event's: the run is cancelled, nothing more
  is recorded for it, the end notes what wasn't recorded, and `perform` fails with `run.recording-failed`. The end's
  `recording` names either the first `seq` that wasn't recorded (`failedAt`, as now) or the notice whose recording
  failed (`notice`, its code), whichever failed first.
- **The run summary carries the run's notices** (`notices`: each with the time it was recorded), absent when it
  recorded none. `troupe status <run>` lists them; `troupe status` adds a count to a run's line when it has any.
- **`logs` returns the run's log, not only its events.** **BREAKING** (protocol version 0, changed in place): the
  `logs` result's `events` becomes `log`, the run's events and its recorded notices in recorded order, each entry
  marked by `kind` (`event` or `run-notice`). Following sends each recorded notice as an update as it's recorded, the
  way it sends events. `troupe logs <run>` shows each recorded notice on its own line among the events, on standard
  output, since it's part of the run's history; the notices `logs` derives when it reads stay on standard error.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runs`: a run's notices are recorded in its stream (which ones, when, in what order); a notice that can't be
  recorded stops the run like a run event; `status` shows a run's notices; `logs` returns them in order with its
  events, and following sends them.
- `client-protocol`: a run summary carries its recorded notices; the `logs` result and updates carry logged notices;
  the summary's `recording` names a notice that wasn't recorded.
- `cli`: `troupe status` and `troupe logs` show a run's recorded notices.

## Impact

- `packages/troupe/src/troupe/core/runs/`: `aggregate.py` (the `Run.Noticed` event and its topic), `perform.py`
  (the recorder records notices in order with events, buffers the ones raised before the start, and treats a failed
  one as a recording failure), `projections.py` (the summary's `notices`, notices in the log), `queries.py` (`logs`
  returns and follows the log).
- `packages/troupe/src/troupe/core/client/messages.py` (`LoggedNotice`, `RunSummary.notices`, `LogsResult.log`,
  the recording's `notice`).
- `packages/troupe/src/troupe/cli/render.py` and `commands.py` (status and logs).
- `protocol/schemas/events/run-noticed.schema.json` (new), `events/run-ended.schema.json` (`recording`),
  `event-record.schema.json` (the topic), `client/run.schema.json`, `client/logs-result.schema.json`,
  `client/logs-update.schema.json`, and their packaged copies.
- `contributing/runs.md` and `contributing/event-store.md` (the topic tables), `docs/the-company/performances-and-runs.md`,
  and the generated `docs/prompt-book/events.md` and CLI reference.
- PR #317 (`estimated-cost`) adds `run.estimate-dropped`, raised through the run host's notice callback, so it's
  recorded with no extra work whichever merges first. Its spec text may need a line saying the notice is kept in the
  run's history; that's checked when the second of the two rebases.
- No spec is added or removed and no Purpose changes, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json`
  needs no update.
