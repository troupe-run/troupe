# runs Specification

## Purpose

Capability: `cap:runs`

Records each run of an actor in the theatre's event store, with lineage, from its first runner event to its derived
outcome, and reads runs back as projections so a person can see what is happening and what happened.

## Requirements

### Requirement: Perform runs one actor and records the run
`perform` SHALL run one actor through its runner on its stage, and record the run in the event store. The run id SHALL
be a new UUID, in canonical lowercase form, minted by `perform`.

#### Scenario: A successful run is recorded
- **WHEN** a person performs an actor whose scripted runner sends `init`, two `turn`s and an `ok` result, and whose
  effect check passes
- **THEN** the run's stream holds, in order, the run's start, one event for each of the four run events in `seq`
  order, and the run's end with outcome `succeeded`

### Requirement: A run is its own stream
Each run SHALL be recorded in its own stream, identified by its run id. The runner's `seq` SHALL be kept in each run
event's payload and SHALL NOT be used as the stream's version.

#### Scenario: Seq is payload
- **WHEN** a run's events are read back
- **THEN** the run's start is version 1, the event with `seq` 0 is version 2, and each event's payload holds its
  `seq`

### Requirement: Init is recorded first
The run's start SHALL be recorded when the runner's `init` event arrives, holding the runner's name and version from
`init`, and `init` SHALL be the first run event recorded. A run that ends without `init` SHALL still record its start,
with no runner name or version, followed by its end.

#### Scenario: The runner's name and version
- **WHEN** a runner's `init` names runner `scripted`, version `0.1.0`
- **THEN** the run's start records that name and version

#### Scenario: A runner that never starts
- **WHEN** a person performs an actor whose runner can't be started
- **THEN** the run's stream holds its start, with no runner name or version, and its end with outcome
  `could-not-start`

### Requirement: Recording a run event out of sequence is refused
A run event whose `seq` isn't the next one the run expects SHALL be refused, and nothing SHALL be written for it. So
SHALL a run event before the run's start or after its end, and a second start or end. These are faults, never
retried.

#### Scenario: A repeated seq
- **WHEN** the run event with `seq` 3 is recorded twice
- **THEN** the second is refused with `run.out-of-sequence`
- **AND** the stream is unchanged

#### Scenario: A gap
- **WHEN** a run event with `seq` 5 is recorded after `seq` 3
- **THEN** it is refused with `run.out-of-sequence`

### Requirement: Who started a run and who acted in it are both recorded
The run's start SHALL have the person who ran `perform` as its actor, resolved through the identity chain, with via
`cli`. The run's events and its end SHALL have the agent being run as their actor (`kind` `agent`, the actor's name as
`id`, source `troupe`), with via `runner`. All of them SHALL share one change id, with the command as their cause.

#### Scenario: Lineage of a run
- **WHEN** a person whose identity resolves to `ada@example.com` from the `vcs` source performs actor `tester`
- **THEN** the run's start has actor `human` `ada@example.com` from `vcs`, via `cli`
- **AND** every run event and the run's end has actor `agent` `tester` from `troupe`, via `runner`
- **AND** all of them have the same change id, and a command cause naming it

#### Scenario: No identity, no run
- **WHEN** a person performs an actor and no identity source answers
- **THEN** `perform` fails with `identity.unresolved`
- **AND** no runner is started and nothing is recorded

### Requirement: The derived outcome is recorded
The run's end SHALL record the outcome the run host derived, with its error, the result, the exit code, how the
runner ended, the transcript's and standard error's references, and the limits in effect.

#### Scenario: A failed run's end
- **WHEN** a run's runner sends an `error` result
- **THEN** the run's end records outcome `failed`, error `run.error-result`, and the transcript's `sha256:` reference

### Requirement: What a run was asked to do is kept
The run's start SHALL record the actor's name, the runner requested, the effect check, the config version it ran
with (the sorted ids of the config stream's heads that the merged config was worked out from), and its workspace. For
a worktree, the workspace SHALL hold the base commit, the worktree's theatre-relative path, whether the theatre was
dirty, and the clone mechanisms used. The direction SHALL be stored as an artifact, and the run's start SHALL
reference it by hash.

#### Scenario: The config a run used
- **WHEN** a run is performed, and the actor's options are changed afterwards
- **THEN** the run's start names the config version from before the change
- **AND** working out config at that version gives the options the run used

#### Scenario: Options are referenced, not inlined
- **WHEN** a run is performed for an actor whose options hold an inline script
- **THEN** no event in the run's stream holds the script itself
- **AND** the run's start references the options through its config version, not as an artifact of their own

#### Scenario: The direction is referenced, not inlined
- **WHEN** a run is performed with a direction
- **THEN** the run's start holds a `sha256:` reference whose artifact is that direction, byte for byte
- **AND** no event in the run's stream holds the direction itself

#### Scenario: A worktree run's workspace
- **WHEN** a worktree run is performed on a clean theatre whose HEAD is commit `c0ffee…`
- **THEN** its start records workspace `worktree`, base `c0ffee…`, the path `.troupe/local/worktrees/<run-id>`, clean,
  and the clone mechanisms used

#### Scenario: A run in place
- **WHEN** a run is performed for an actor whose workspace is `theatre`
- **THEN** its start records workspace `theatre`, with no base, path or clone mechanisms

### Requirement: Ctrl-C cancels the run, and the cancel is recorded
An interrupt during `perform` SHALL cancel the run through the run host, and `perform` SHALL record the run's end.
Further interrupts while it is cancelling SHALL be announced and SHALL NOT stop `perform` before the run's end is
recorded.

#### Scenario: One Ctrl-C
- **WHEN** a person presses Ctrl-C while a run is hanging
- **THEN** the notice `run.cancelling` is shown
- **AND** the run's end records outcome `cancelled`

#### Scenario: Ctrl-C twice
- **WHEN** a person presses Ctrl-C twice while a runner ignores cancel
- **THEN** the notice is shown again
- **AND** the runner is killed after `RUNNER_CANCEL_GRACE_SECONDS`, and the run's end is recorded

### Requirement: A recording failure stops the run and is reported
If a run event can't be recorded, `perform` SHALL cancel the run, record no further run events, and still try to
record the run's end, noting the first `seq` that wasn't recorded and why. It SHALL then fail with
`run.recording-failed`, naming the run, the error and the transcript's reference.

#### Scenario: The store refuses a write mid-run
- **WHEN** recording the run event with `seq` 2 fails
- **THEN** the run is cancelled
- **AND** the run's end records that recording failed at `seq` 2, with the error
- **AND** `perform` fails with `run.recording-failed`

### Requirement: A run's state is derived, never recorded as running
A run SHALL be `ended` when its end is recorded. Otherwise it SHALL be `running` while the `perform` that runs it is
alive in this clone, `interrupted` when that `perform` has gone without recording an end, and `unfinished-elsewhere`
when it was started in another clone. Nothing SHALL be recorded on behalf of an interrupted run.

#### Scenario: Perform is killed
- **WHEN** the process running `perform` is killed while its run is going
- **THEN** `status` shows the run as `interrupted`, with the notice `run.interrupted`
- **AND** no end is recorded for it

#### Scenario: A run from another clone
- **WHEN** a run's start and events arrive by a merge, with no end, from a clone where it was started
- **THEN** `status` shows the run as `unfinished-elsewhere`, with the notice `run.unfinished-elsewhere`

### Requirement: Status reads runs from a projection
`status` SHALL list the most recent runs, newest first, up to a named default limit that a request can lower or
raise. Given a run, it SHALL show that run's summary: its actor, who started it, its runner, its stage, its
workspace, its state, its outcome and error, its changes and their state, its event count, its times, and its
transcript and standard error references.

#### Scenario: Status while a run is going
- **WHEN** a person runs `status` in another terminal while a run is going
- **THEN** the run is listed with state `running` and the number of events recorded so far

#### Scenario: Status after the run
- **WHEN** a person runs `status <run>` after the run ended `failed`
- **THEN** it shows the outcome `failed` and the run's error

#### Scenario: Status of a run with pending changes
- **WHEN** a person runs `status <run>` after a worktree run that changed two files
- **THEN** it shows workspace `worktree`, changes `pending`, the diff's reference, the counts and the worktree's path

### Requirement: Logs read a run's events in order
`logs` SHALL return a run's events in `seq` order, each with the time it was recorded. With `follow`, it SHALL send
each new event as an update as it is recorded, and SHALL stop when the run ends or stops being `running`, saying why.

#### Scenario: Logs of an ended run
- **WHEN** a person asks for the logs of a run with five events
- **THEN** the five events are returned in `seq` order

#### Scenario: Following a run
- **WHEN** a person follows the logs of a running run from another terminal
- **THEN** each event is shown as it is recorded
- **AND** following stops when the run's end is recorded

#### Scenario: Following shows events as they are recorded
- **WHEN** a person follows a running run's logs, with the store's fallback poll interval set to 60 s, and the
  runner sends three events
- **THEN** each event is shown, and the median delay, measured from when the writer's append returned rather than
  from the event's recorded time, is under 0.5 s

#### Scenario: Following an interrupted run
- **WHEN** a person follows the logs of a run that is `interrupted`
- **THEN** the recorded events are shown and following stops at once with the notice `run.interrupted`

### Requirement: Runs are named by id or unique prefix
A query SHALL accept a run's full id, or a prefix of at least 8 hex digits that matches exactly one run. A prefix that
matches none SHALL be refused with `run.not-found`, and one that matches several with `run.ambiguous-id`, listing
them.

#### Scenario: An ambiguous prefix
- **WHEN** two runs' ids both start with `1a2b3c4d` and a person asks for `status 1a2b3c4d`
- **THEN** it is refused with `run.ambiguous-id`, listing both runs

### Requirement: Run settings are named
Every limit or default `status` and `logs` use SHALL be a named setting with its default in one place.

#### Scenario: The status limit
- **WHEN** `status` lists runs without a limit in its request
- **THEN** it lists at most `STATUS_RUNS_LIMIT` runs

### Requirement: Following subscribes to the store's events
Following SHALL subscribe to the event store's events through the store port, and SHALL have no timer of its own for
finding new events. How the store learns of other writers' events is the store's concern, not following's.

#### Scenario: Nothing is recorded while following
- **WHEN** a person follows a running run's logs, with `SUBSCRIBE_CHECK_SECONDS` set to 60 s, and the run records
  nothing for 2 s
- **THEN** no segment is read in that time

#### Scenario: The store's subscription can only poll
- **WHEN** a person follows a running run's logs and the store's subscription can only poll
- **THEN** the notice `events.subscription-polling` is sent as an update when following starts, and is in the result
- **AND** each event is still sent as it is found by the store's fallback poll

### Requirement: Following notices a run that stops without an end
While following, a run whose `perform` stops without recording an end SHALL be noticed within
`LOGS_LEASE_CHECK_SECONDS`, though nothing was written. Following SHALL then stop with the notice `run.interrupted`.

#### Scenario: Perform dies while the run is followed
- **WHEN** a person follows a running run's logs and its `perform` is killed
- **THEN** following stops within `LOGS_LEASE_CHECK_SECONDS`, plus the time to read the run, with the run `interrupted`
  and the notice `run.interrupted`

### Requirement: Following's limits are named settings
The interval at which following checks a run's lease SHALL be the setting `LOGS_LEASE_CHECK_SECONDS`, with its
default in troupe's one named place for defaults, and overridable. Following SHALL have no poll interval of its own.

#### Scenario: The documentation lists following's defaults
- **WHEN** the runs documentation is checked against the defaults
- **THEN** it lists `LOGS_LEASE_CHECK_SECONDS` with its value, and no `LOGS_FOLLOW_POLL_SECONDS`

### Requirement: A run's start leaves out a runner that never reported
A run's start SHALL record the runner's reported name and version when the runner sent an init, and SHALL leave the
reported runner out when it never did.

#### Scenario: A runner that never sent init
- **WHEN** a run ends before its runner sends an init
- **THEN** its start has no `runner_reported`, and the run's summary has no `runner.reported`

### Requirement: A run's end records what happened and leaves out what didn't
A run's end SHALL record the outcome's `exitCode`, `transcript` and `stderr` exactly when the runner started, that
is when `ending` isn't `never-started`. It SHALL leave out `error` when the outcome has none, `result` when the runner
sent none, and `recording` when recording didn't fail. It SHALL record `changes` exactly when the run's workspace was
a worktree that was made.

#### Scenario: A run whose runner never started
- **WHEN** a run's runner can't be started
- **THEN** its end records outcome `could-not-start` and ending `never-started`, with an `error` and no `exitCode`,
  `transcript`, `stderr`, `result` or `recording`

#### Scenario: A run that succeeded
- **WHEN** a run's runner sends an `ok` result and exits with code 0
- **THEN** its end records `exitCode` 0, the `transcript`, `stderr` and `result`, and no `error` or `recording`

#### Scenario: An end that contradicts its ending
- **WHEN** a run's end payload has ending `exited` and no `exitCode`, or ending `never-started` and a `transcript`
- **THEN** it doesn't validate against the run's end schema

#### Scenario: A worktree run whose runner never started
- **WHEN** a worktree run's runner can't be started
- **THEN** its end still records `changes`, with nothing changed, and the worktree is kept until it is discarded

#### Scenario: A run in place has no changes
- **WHEN** a run whose workspace is `theatre` ends
- **THEN** its end has no `changes`

### Requirement: A recording failure leaves out what it can't name
`run.recording-failed` SHALL leave out `failedAt` when only the run's end failed to record, `endError` when the end
was recorded, and `transcript` when the runner never started.

#### Scenario: Only the end fails to record
- **WHEN** every run event is recorded and recording the run's end fails
- **THEN** `perform` fails with `run.recording-failed`, whose details have `endError` and no `failedAt`

#### Scenario: A run event fails to record and the end is recorded
- **WHEN** recording the run event with `seq` 2 fails and the run's end is recorded
- **THEN** the details have `failedAt` 2 and no `endError`

### Requirement: A run uses the actor as config defines it
`perform` SHALL take the actor's runner, options, effect check and character from the merged config, as it is when
the run starts. A request SHALL name only the actor, the direction and whether to rehearse.

#### Scenario: The character reaches the runner
- **WHEN** config gives `tester` a character, and a person performs `tester` with the scripted runner and a script
  that checks the character it receives
- **THEN** the run succeeds, because the runner received exactly that character

#### Scenario: Config changed between two runs
- **WHEN** a person performs `tester`, changes its runner's options, and performs it again
- **THEN** the second run uses the new options

### Requirement: The effect check reads the run's workspace
The effect check's paths SHALL be read in the run's workspace: under the worktree for a worktree run, and under the
theatre for a run in place.

#### Scenario: An expected file in the worktree
- **WHEN** a worktree actor with `expect: ["out/hello.txt"]` writes `out/hello.txt` in its worktree and sends `ok`
- **THEN** the effect check passes and the run `succeeded`, though the theatre has no `out/hello.txt`

### Requirement: A worktree is made only after every check passes
`perform` SHALL make a run's worktree only after the identity, policy, stage and config checks have all passed, and
before the runner starts. A failure to make the worktree SHALL refuse the perform, remove whatever part of the
worktree was made, and record nothing.

#### Scenario: A refused perform makes no worktree
- **WHEN** a perform is refused with `stage.effects-unenforced`
- **THEN** no directory is made under `.troupe/local/worktrees/`

#### Scenario: Making the worktree fails
- **WHEN** git fails while a run's worktree is being made
- **THEN** perform fails with that error, no event is recorded, and no worktree for the run is left registered with
  git or on disk

### Requirement: Perform knows the runners troupe ships by name
`perform` SHALL turn an actor's runner name into a command line only through troupe's table of runners it ships,
which SHALL name `scripted` and `claude-code`. Any other name SHALL be refused with `runner.unknown`, naming the
runners troupe knows, before anything is recorded.

#### Scenario: The Claude Code runner
- **WHEN** a person performs an actor whose runner is `claude-code`
- **THEN** `perform` starts the Claude Code runner

#### Scenario: A runner troupe doesn't ship
- **WHEN** a person performs an actor whose runner is `codex`
- **THEN** it is refused with `runner.unknown`, naming `claude-code` and `scripted`, and nothing is recorded

### Requirement: Perform passes a runner only the variables it is known to need
`perform` SHALL start a runner with the environment variables troupe's runner table names for it, each taken from
`perform`'s own environment when set there, and SHALL pass no others. The scripted runner SHALL be named none. The
Claude Code runner SHALL be named what Claude Code needs to run and find the person's login.

#### Scenario: The Claude Code runner gets its login's variables
- **WHEN** `perform` runs with `PATH`, `HOME` and `CLAUDE_CODE_OAUTH_TOKEN` set, and performs a `claude-code` actor
- **THEN** the runner's environment holds those three with the same values

#### Scenario: Nothing else reaches it
- **WHEN** `perform` runs with `AWS_SECRET_ACCESS_KEY` set, and performs a `claude-code` actor
- **THEN** the runner's environment has no `AWS_SECRET_ACCESS_KEY`

#### Scenario: A name that isn't set
- **WHEN** `ANTHROPIC_API_KEY` isn't set in `perform`'s environment
- **THEN** the runner's environment has no `ANTHROPIC_API_KEY`, rather than an empty one

#### Scenario: The scripted runner gets nothing new
- **WHEN** `perform` runs with `PATH` set, and performs a `scripted` actor
- **THEN** the runner's environment has only the platform minimum
