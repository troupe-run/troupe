# Delta: runs

## ADDED Requirements

### Requirement: A run's notices are recorded in its stream
Every notice `perform` raises for a run, from when it mints the run's id until the run's end is recorded, SHALL be
recorded in the run's stream as its own event holding the notice as protocol data, in the order troupe raised it
among the run's events. A notice raised before the run's start is recorded SHALL be recorded straight after it.
Recording a notice SHALL NOT delay its live update.

#### Scenario: A silence and a retry are kept
- **WHEN** a run's runner sends `init`, falls silent past the silence threshold, sends a `retry` event, then an `ok`
  result
- **THEN** the run's stream holds, in order, the start, `init`, the `run.silent` notice, the `retry` event, the
  `run.retrying` notice, the result, and the end
- **AND** each notice was also sent to the caller as an update while the run went

#### Scenario: A notice raised before the start
- **WHEN** a worktree run is performed while the theatre has uncommitted changes
- **THEN** the `workspace.uncommitted-unseen` notice is recorded straight after the run's start, before its worktree
  is recorded as made

#### Scenario: A notice raised after the runner ends
- **WHEN** a run's scratch directory can't be removed when its runner ends
- **THEN** the `run.scratch-not-removed` notice is recorded before the run's end

### Requirement: Only a run's own notices are recorded in it
The config notices `perform` raises before it mints the run's id, the event store's notices, and the notices `status`
and `logs` derive when they read a run SHALL NOT be recorded in a run's stream. Nor SHALL the notices `accept` and
`discard` raise, which their results carry.

#### Scenario: A config file rewritten before the run
- **WHEN** `perform` rewrites a config file and raises `config.file-rewritten`, then runs the actor
- **THEN** the notice is sent to the caller, and the run's stream holds no notice for it

#### Scenario: An interrupted run read back
- **WHEN** `status` reads a run that is `interrupted`
- **THEN** it returns the notice `run.interrupted`, and nothing is recorded in the run's stream

### Requirement: A run's notices are recorded only between its start and its end
A notice SHALL be recorded in a run's stream only after the run's start and before its end. A notice recorded
outside that span SHALL be refused as out of sequence, and nothing written for it.

#### Scenario: A notice after the end
- **WHEN** a notice is recorded for a run whose end is already recorded
- **THEN** it is refused with `run.out-of-sequence`, and the run's stream is unchanged

## MODIFIED Requirements

### Requirement: Who started a run and who acted in it are both recorded
The run's start SHALL have the person who ran `perform` as its actor, resolved through the identity chain, with via
`cli`. So SHALL each notice recorded in the run, since troupe raises it for the person, not the agent. The run's events
and its end SHALL have the agent being run as their actor (`kind` `agent`, the actor's name as `id`, source `troupe`),
with via `runner`. All of them SHALL share one change id, with the command as their cause.

#### Scenario: Lineage of a run
- **WHEN** a person whose identity resolves to `ada@example.com` from the `vcs` source performs actor `tester`
- **THEN** the run's start has actor `human` `ada@example.com` from `vcs`, via `cli`
- **AND** every run event and the run's end has actor `agent` `tester` from `troupe`, via `runner`
- **AND** all of them have the same change id, and a command cause naming it

#### Scenario: Lineage of a recorded notice
- **WHEN** a person whose identity resolves to `ada@example.com` performs actor `tester`, and the run falls silent
- **THEN** the recorded `run.silent` notice has actor `human` `ada@example.com`, via `cli`, and the run's change id

#### Scenario: No identity, no run
- **WHEN** a person performs an actor and no identity source answers
- **THEN** `perform` fails with `identity.unresolved`
- **AND** no runner is started and nothing is recorded

### Requirement: A recording failure stops the run and is reported
If a run event or a notice can't be recorded, `perform` SHALL cancel the run, record no further run events or notices,
and still try to record the run's end, noting what wasn't recorded first, the run event's `seq` or the notice's code,
and why. It SHALL still send every notice live. It SHALL then fail with `run.recording-failed`, naming the run, the
error and the transcript's reference.

#### Scenario: The store refuses a write mid-run
- **WHEN** recording the run event with `seq` 2 fails
- **THEN** the run is cancelled
- **AND** the run's end records that recording failed at `seq` 2, with the error
- **AND** `perform` fails with `run.recording-failed`

#### Scenario: The store refuses a notice
- **WHEN** recording the `run.silent` notice fails while the run is going
- **THEN** the run is cancelled, and no later run event or notice is recorded
- **AND** the run's end records that recording failed at the notice `run.silent`, with the error, and no `seq`
- **AND** `perform` fails with `run.recording-failed`

### Requirement: A recording failure leaves out what it can't name
`run.recording-failed` SHALL leave out `failedAt` when no run event failed to record, `notice` when no notice failed to
record, `endError` when the end was recorded, and `transcript` when the runner never started. It SHALL NOT carry both
`failedAt` and `notice`: it names whichever failed first.

#### Scenario: Only the end fails to record
- **WHEN** every run event is recorded and recording the run's end fails
- **THEN** `perform` fails with `run.recording-failed`, whose details have `endError` and no `failedAt` or `notice`

#### Scenario: A run event fails to record and the end is recorded
- **WHEN** recording the run event with `seq` 2 fails and the run's end is recorded
- **THEN** the details have `failedAt` 2 and no `notice` or `endError`

#### Scenario: A notice fails to record and the end is recorded
- **WHEN** recording the `run.scratch-not-removed` notice fails and the run's end is recorded
- **THEN** the details have `notice` `run.scratch-not-removed` and no `failedAt` or `endError`

### Requirement: Status reads runs from a projection
`status` SHALL list the most recent runs, newest first, up to a named default limit that a request can lower or
raise. Given a run, it SHALL show that run's summary: its actor, who started it, its runner, its stage, its
workspace, its state, its outcome and error, its changes and their state, its event count, its recorded notices, its
times, and its transcript and standard error references.

#### Scenario: Status while a run is going
- **WHEN** a person runs `status` in another terminal while a run is going
- **THEN** the run is listed with state `running` and the number of events recorded so far

#### Scenario: Status after the run
- **WHEN** a person runs `status <run>` after the run ended `failed`
- **THEN** it shows the outcome `failed` and the run's error

#### Scenario: Status of a run with pending changes
- **WHEN** a person runs `status <run>` after a worktree run that changed two files
- **THEN** it shows workspace `worktree`, changes `pending`, the diff's reference, the counts and the worktree's path

#### Scenario: Status of a run that raised notices
- **WHEN** a person runs `status <run>` after an unattended run that fell silent once and retried once
- **THEN** its summary holds the `run.silent` and `run.retrying` notices, in the order they were raised, each with
  the time it was recorded

#### Scenario: Status of an interrupted run that raised a notice
- **WHEN** a person runs `status <run>` for an `interrupted` run that recorded a `run.silent` notice before its
  `perform` was killed
- **THEN** its summary holds the `run.silent` notice

### Requirement: Logs read a run's events in order
`logs` SHALL return a run's log: its events in `seq` order and its recorded notices, in the order they were recorded,
each with the time it was recorded. With `follow`, it SHALL send each new event and each new recorded notice as an
update as it is recorded, and SHALL stop when the run ends or stops being `running`, saying why.

#### Scenario: Logs of an ended run
- **WHEN** a person asks for the logs of a run with five events
- **THEN** the five events are returned in `seq` order

#### Scenario: Logs of a run that raised a notice
- **WHEN** a person asks for the logs of a run that sent `init`, a `retry` event and a result
- **THEN** the log holds `init`, the `retry` event, the `run.retrying` notice and the result, in that order

#### Scenario: Following a run
- **WHEN** a person follows the logs of a running run from another terminal
- **THEN** each event is shown as it is recorded
- **AND** following stops when the run's end is recorded

#### Scenario: Following shows a notice as it is recorded
- **WHEN** a person follows the logs of a running run from another terminal, and the run falls silent
- **THEN** the `run.silent` notice is sent as an update once it is recorded, among the run's events

#### Scenario: Following shows events as they are recorded
- **WHEN** a person follows a running run's logs from another process, with the store's fallback poll and check
  intervals and following's run check all set to 60 s, and the run's process records each event only once following
  has shown the event before it, five times, and then, while no delay so far is under 0.5 s, once more at a time for
  up to a 60 s allowance for a slow stretch
- **THEN** each event is shown before the next one is recorded, so following woke on that event's own write rather
  than on a later event or a timer
- **AND** the fastest of the delays, measured from when the writer's append returned rather than from the event's
  recorded time, is under 0.5 s, and the median of the first five is within 0.5 s plus an allowance for a loaded
  machine

#### Scenario: Following an interrupted run
- **WHEN** a person follows the logs of a run that is `interrupted`
- **THEN** the recorded events are shown and following stops at once with the notice `run.interrupted`
