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

### Requirement: A run's start is recorded before its runner starts
The run's start SHALL be recorded before its runner starts, and before its workspace is made, once every check that
can refuse the run has passed. The runner's `init` event SHALL be the first run event recorded, and the run's
reported runner name and version SHALL be read from it. A run that ends without `init` SHALL have its start followed
by its end.

#### Scenario: The runner's name and version
- **WHEN** a runner's `init` names runner `scripted`, version `0.1.0`
- **THEN** the run's first reported event is that `init`, and the run's summary reports runner `scripted`, version
  `0.1.0`

#### Scenario: A runner that never starts
- **WHEN** a person performs an actor whose runner can't be started
- **THEN** the run's stream holds its start and its end, with outcome `could-not-start`

#### Scenario: The start comes before the runner
- **WHEN** a person performs an actor, and the run is read while its runner is starting, before it sends `init`
- **THEN** the run's start is recorded, and `status` shows the run as `running`

#### Scenario: Killed before init
- **WHEN** a run's `perform` is killed after its runner started and before the runner sent `init`
- **THEN** `status` shows the run as `interrupted`, with the notice `run.interrupted`

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

### Requirement: The derived outcome is recorded
The run's end SHALL record the outcome the run host derived, with its error, the result, the exit code, how the
runner ended, the transcript's and standard error's references, and the limits in effect.

#### Scenario: A failed run's end
- **WHEN** a run's runner sends an `error` result
- **THEN** the run's end records outcome `failed`, error `run.error-result`, and the transcript's `sha256:` reference

### Requirement: What a run was asked to do is kept
The run's start SHALL record the actor's name, the runner requested, the effect check, the config version it ran
with (the sorted ids of the config stream's heads that the merged config was worked out from), and its workspace. For
a worktree, the workspace SHALL hold the base commit, the worktree's theatre-relative path and whether the theatre was
dirty. The direction SHALL be stored as an artifact before the start is recorded, and the run's start SHALL
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
- **THEN** its start records workspace `worktree`, base `c0ffee…`, the path `.troupe/local/worktrees/<run-id>` and
  clean, and no clone mechanisms

#### Scenario: A run in place
- **WHEN** a run is performed for an actor whose workspace is `theatre`
- **THEN** its start records workspace `theatre`, with no base, path or clone mechanisms

#### Scenario: The direction can't be stored
- **WHEN** storing a run's direction as an artifact fails
- **THEN** `perform` fails with the artifact store's error
- **AND** nothing is recorded, and no worktree is made

### Requirement: A run's start always records its workspace
A run's start SHALL always record its workspace, and SHALL NOT record a worktree's clone mechanisms, which are recorded
once the worktree is made. A start without its workspace, or with clone mechanisms in it, SHALL NOT validate.

#### Scenario: A start without its workspace
- **WHEN** a run's start payload has no `workspace`
- **THEN** it doesn't validate against the run's start schema

#### Scenario: A start that holds clone mechanisms
- **WHEN** a worktree run's start payload holds `clones` in its workspace
- **THEN** it doesn't validate against the run's start schema, since a run's clone mechanisms are recorded only when
  its worktree is made

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

### Requirement: The reported runner comes from the run's init
A run's summary SHALL report the runner's name and version from its `init` event when the runner sent one, and SHALL
leave the reported runner out when it never did. The run's start SHALL NOT record the reported runner.

#### Scenario: A runner that never sent init
- **WHEN** a run ends before its runner sends an init
- **THEN** its start has no `runner_reported`, and the run's summary has no `runner.reported`

#### Scenario: A start that names the reported runner
- **WHEN** a run's start payload holds `runner_reported`
- **THEN** it doesn't validate against the run's start schema

### Requirement: A run's end records what happened and leaves out what didn't
A run's end SHALL record the outcome's `exitCode`, `transcript`, `transcriptFormat` and `stderr` exactly when the
runner started, that is when `ending` isn't `never-started`. It SHALL leave out `error` when the outcome has none,
`result` when the runner sent none, and `recording` when recording didn't fail. It SHALL record `changes` exactly when
the run's workspace was a worktree that was made.

#### Scenario: A run whose runner never started
- **WHEN** a run's runner can't be started
- **THEN** its end records outcome `could-not-start` and ending `never-started`, with an `error` and no `exitCode`,
  `transcript`, `transcriptFormat`, `stderr`, `result` or `recording`

#### Scenario: A run that succeeded
- **WHEN** a run's runner sends an `ok` result and exits with code 0
- **THEN** its end records `exitCode` 0, the `transcript`, its `transcriptFormat`, `stderr` and `result`, and no
  `error` or `recording`

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
`run.recording-failed` SHALL leave out `failedAt` when no run event failed to record, `notice` when no notice failed to
record, `endError` when the end was recorded, and `transcript` and `transcriptFormat` when the runner never started.
It SHALL carry `transcriptFormat` exactly when it carries `transcript`, and SHALL NOT carry both `failedAt` and
`notice`: it names whichever failed first.

#### Scenario: Only the end fails to record
- **WHEN** every run event is recorded and recording the run's end fails
- **THEN** `perform` fails with `run.recording-failed`, whose details have `endError` and no `failedAt` or `notice`
- **AND** its details carry the transcript's reference and its `transcriptFormat`

#### Scenario: A run event fails to record and the end is recorded
- **WHEN** recording the run event with `seq` 2 fails and the run's end is recorded
- **THEN** the details have `failedAt` 2 and no `notice` or `endError`

#### Scenario: A notice fails to record and the end is recorded
- **WHEN** recording the `run.scratch-not-removed` notice fails and the run's end is recorded
- **THEN** the details have `notice` `run.scratch-not-removed` and no `failedAt` or `endError`

### Requirement: A run uses the actor as config defines it
`perform` SHALL take the actor's runner, options, effects, effect check, character, runtime and model from the merged
config, as it is when the run starts, and resolve the runtime as spec: runtimes says. A request SHALL name only the
actor, the direction and whether to rehearse.

#### Scenario: The character reaches the runner
- **WHEN** config gives `tester` a character, and a person performs `tester` with the scripted runner and a script
  that checks the character it receives
- **THEN** the run succeeds, because the runner received exactly that character

#### Scenario: Config changed between two runs
- **WHEN** a person performs `tester`, changes its runner's options, and performs it again
- **THEN** the second run uses the new options

#### Scenario: The effects reach the runner
- **WHEN** config gives `tester` `effects.write: ["out/**"]` and a person performs it
- **THEN** the runner's `run/start` carries `write: ["out/**"]` and empty `delete` and `move`

#### Scenario: The runtime reaches the runner
- **WHEN** config gives `tester` the runtime `ollama` and the model `llama3.2`, and a person performs it with a script
  that checks the runtime it receives
- **THEN** the run succeeds, because the runner received the endpoint `http://127.0.0.1:11434` and the model
  `llama3.2`

### Requirement: The effect check reads the run's workspace
The effect check's paths SHALL be read in the run's workspace: under the worktree for a worktree run, and under the
theatre for a run in place.

#### Scenario: An expected file in the worktree
- **WHEN** a worktree actor with `expect: ["out/hello.txt"]` writes `out/hello.txt` in its worktree and sends `ok`
- **THEN** the effect check passes and the run `succeeded`, though the theatre has no `out/hello.txt`

### Requirement: A worktree is made only after every check passes
`perform` SHALL make a run's worktree only after the identity, policy, stage and config checks have all passed and
the run's start is recorded, and before the runner starts. A failure to make the worktree SHALL fail the perform,
remove whatever part of the worktree was made, and end the run.

#### Scenario: A refused perform makes no worktree
- **WHEN** a perform is refused with `stage.effects-unenforced`
- **THEN** no directory is made under `.troupe/local/worktrees/`, and nothing is recorded

#### Scenario: Making the worktree fails
- **WHEN** git fails while a run's worktree is being made
- **THEN** perform fails with that error, and no worktree for the run is left registered with git or on disk
- **AND** the run's stream holds its start and its end, with outcome `could-not-start` and that error

### Requirement: Perform knows the runners troupe ships by name
`perform` SHALL turn an actor's runner name into a command line only through troupe's table of runners it ships,
which SHALL name `scripted`, `claude-code`, `ollama` and `openai`, and say for each whether it takes a runtime:
`required`, `optional` or `none`, and whether it is installed through the `troupe-run` extra named after it rather
than the base install. Any other name SHALL be refused with `runner.unknown`, naming the runners troupe knows, before
anything is recorded.

#### Scenario: The Claude Code runner
- **WHEN** a person performs an actor whose runner is `claude-code`
- **THEN** `perform` starts the Claude Code runner

#### Scenario: The Ollama runner
- **WHEN** a person performs an actor whose runner is `ollama` and whose runtime is `ollama`
- **THEN** `perform` starts the Ollama runner, its `run/start` carries the runtime `ollama` with the actor's model,
  and the run's start records that runtime

#### Scenario: The OpenAI runner
- **WHEN** a person performs an actor whose runner is `openai`
- **THEN** `perform` starts the OpenAI runner

#### Scenario: A runner troupe doesn't ship
- **WHEN** a person performs an actor whose runner is `codex`
- **THEN** it is refused with `runner.unknown`, naming `claude-code`, `ollama`, `openai` and `scripted`, and
  nothing is recorded

#### Scenario: What each runner takes
- **WHEN** troupe's runner table is read
- **THEN** `claude-code` takes no runtime, `scripted` takes one optionally, and `ollama` and `openai` require one

#### Scenario: Which extra each runner needs
- **WHEN** troupe's runner table is read while every runner plugin depends only on the SDK
- **THEN** no runner is in an extra

#### Scenario: The table and the bundle agree
- **WHEN** troupe's runner table says a runner is in the base install while `troupe-run` has it in an extra, or the
  reverse
- **THEN** `scripts/check.py` fails, naming the runner, the table and `packages/troupe-run/pyproject.toml`

### Requirement: Perform passes a runner only the variables it is known to need
`perform` SHALL start a runner with only the environment variables troupe's runner table names for it, each taken from
`perform`'s own environment when set there, plus `TROUPE_RUNTIME_CREDENTIAL` holding the credential when the run's
runtime has one. The scripted and Ollama runners SHALL be named none, the Claude Code runner what Claude Code needs to
run and find the person's login, and the OpenAI runner only what it needs to reach a service through a proxy and trust
its certificate.

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

#### Scenario: The Ollama runner gets nothing new
- **WHEN** `perform` runs with `PATH`, `OLLAMA_HOST` and `HTTPS_PROXY` set, and performs an `ollama` actor
- **THEN** the runner's environment has only the platform minimum

#### Scenario: The credential under troupe's name only
- **WHEN** `MY_KEY` holds a key, a runtime's credential names `MY_KEY`, and a `scripted` actor on it is performed
- **THEN** the runner's environment holds the key as `TROUPE_RUNTIME_CREDENTIAL`, and has no `MY_KEY`

#### Scenario: The OpenAI runner gets its proxy, its certificates and its credential
- **WHEN** `perform` runs with `HTTPS_PROXY`, `SSL_CERT_FILE` and `OPENAI_API_KEY` set, and performs an `openai`
  actor on the runtime `openai`
- **THEN** the runner's environment holds `HTTPS_PROXY` and `SSL_CERT_FILE` with the same values, and the key as
  `TROUPE_RUNTIME_CREDENTIAL`, and has no `OPENAI_API_KEY`

### Requirement: A failure before the runner starts ends the run
When anything fails after a run's start is recorded and before its runner starts, such as making its worktree or
reading the repository's shared state, the run's end SHALL be recorded with outcome `could-not-start`, the failure as
its error, and the runner's ending `never-started`. `perform` SHALL then fail with that error, as it did before the
start came first.

#### Scenario: Reading the shared state fails
- **WHEN** a worktree run's worktree is made, and git then fails while troupe reads the repository's shared state
- **THEN** perform fails with git's error
- **AND** the run's stream holds its start, its worktree's clone mechanisms and its end, with outcome
  `could-not-start` and git's error, and no runner was started

#### Scenario: Ending the run fails too
- **WHEN** making a run's worktree fails, and recording the run's end then fails
- **THEN** perform fails with `run.recording-failed`, naming the run, the error that stopped the worktree, and the
  error recording its end
- **AND** `status` shows the run as `interrupted`, and it can be discarded

### Requirement: Perform's effects check shows the declaration
A rehearsed `perform` SHALL show the effects the run would start with, and, when a run's effect check fails because
of the audit, `perform` SHALL show each change outside the declaration with the effect it needed, on every surface,
as structured data.

#### Scenario: A rehearsal shows the effects
- **WHEN** a person rehearses performing `tester`, which declares `write` for `out/**`
- **THEN** the rehearsal shows `effects: write out/**`, and a read-only actor's shows that it's read-only

#### Scenario: A failed audit on the command line
- **WHEN** a run fails its audit for `src/a.py`
- **THEN** `troupe perform` reports the outcome `failed`, naming `src/a.py`, `write`, and the `troupe config set` that
  would declare it

### Requirement: A run's end records its audit whenever its runner started
A run's end SHALL record `outcome.audit` exactly when its runner started. It SHALL hold either `outside`, every change
outside the declaration in path order, each with `path`, `change`, `needs` and, for a move, `to`, and empty when every
change was declared; or `error`, when the audit couldn't read the workspace. An end whose runner started and that has
no `audit` SHALL NOT validate.

#### Scenario: A cancelled worktree run's end
- **WHEN** a worktree run whose actor declares no effects writes `src/a.py` and is cancelled
- **THEN** its end records outcome `cancelled`, and `outcome.audit.outside` holds `src/a.py`, `added`, needing
  `write`, alongside its `changes`

#### Scenario: A run that succeeded
- **WHEN** a run's changes are all declared and it succeeds
- **THEN** its end records `outcome.audit` with an empty `outside`

#### Scenario: A run whose runner never started has no audit
- **WHEN** a run's runner can't be started
- **THEN** its end has no `outcome.audit`

#### Scenario: An audit that contradicts itself
- **WHEN** a run's end payload has an `outcome.audit` with both `outside` and `error`, or with neither
- **THEN** it doesn't validate against the run's end schema

#### Scenario: An end without its audit
- **WHEN** a run's end payload has ending `exited` or `killed` and no `outcome.audit`
- **THEN** it doesn't validate against the run's end schema

### Requirement: A run's start records its runtime and where each value came from
When an actor names a runtime, the run's start SHALL record the runtime's name, its endpoint and model, each with its
source, when it has a credential, the variable's name and its source, and when the run's model has a price, that price
with its source. It SHALL NOT record the credential's value.

#### Scenario: A run on a theatre-chosen endpoint
- **WHEN** config sets `runtimes.openai.endpoint=https://gateway.example/v1` and an actor on `openai` is performed
- **THEN** the run's start records the endpoint `https://gateway.example/v1` with source `theatre`, and the variable
  `OPENAI_API_KEY` with source `default`

#### Scenario: A run on a priced model
- **WHEN** config prices `gpt-test` on `openai` and an actor on `openai` with the model `gpt-test` is performed
- **THEN** the run's start records that price with source `theatre`, the same price its `run/start` carried

#### Scenario: A run with no runtime
- **WHEN** an actor that names no runtime is performed
- **THEN** the run's start has no `runtime` field

### Requirement: troupe masks the credential in everything it keeps from a run
troupe SHALL replace the run's credential value with `[credential]` in every run event, transcript record and byte of
kept standard error it stores, and in any error or notice, before it is written or sent, including where the value
is split across reads.

#### Scenario: An echoed key in a log event
- **WHEN** a runner sends a `log` event whose message holds the credential
- **THEN** the recorded event's message holds `[credential]` in its place

#### Scenario: A key split across two reads of standard error
- **WHEN** a runner writes the credential to standard error in two writes, split in the middle
- **THEN** the kept standard error holds `[credential]`, and no part of the value that the split left on either side

#### Scenario: The JSON-escaped form
- **WHEN** a credential holds `/` and a runner sends it inside JSON text as `\/`
- **THEN** that form is masked too

### Requirement: A rehearsal shows the run's runtime
A rehearsed `perform` SHALL show the runtime the run would use, with each value's source, whether its credential's
variable is set, and the price of its model when it has one, and SHALL refuse what perform would refuse about the
runtime.

#### Scenario: A rehearsal on openai
- **WHEN** a person rehearses an actor on `openai` and `OPENAI_API_KEY` is set
- **THEN** the rehearsal shows the endpoint, the model and the variable `OPENAI_API_KEY`, set, each with its source,
  and no part of the key

#### Scenario: A rehearsal on a priced model
- **WHEN** a person rehearses an actor on `openai` whose model config prices
- **THEN** the rehearsal shows that price with source `theatre`

### Requirement: A run's end says which form its transcript is
`transcriptFormat` SHALL be `kinds` when the runner accepted `transcript-kinds`, and `native` otherwise. A run's end
with a `transcript` and no `transcriptFormat`, or the reverse, SHALL NOT validate.

#### Scenario: A run that used kinds
- **WHEN** a run's runner accepted `transcript-kinds` and the run ends
- **THEN** its end records `transcriptFormat` `kinds`

#### Scenario: A Claude Code run
- **WHEN** a Claude Code run ends
- **THEN** its end records `transcriptFormat` `native`

#### Scenario: A transcript without its format
- **WHEN** a run's end payload has ending `exited`, a `transcript` and no `transcriptFormat`
- **THEN** it doesn't validate against the run's end schema

#### Scenario: A format without a transcript
- **WHEN** a run's end payload has ending `never-started` and a `transcriptFormat`
- **THEN** it doesn't validate against the run's end schema

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

### Requirement: Perform refuses an actor whose runner isn't installed
When an actor's runner is in troupe's table but its package isn't installed, `perform` SHALL refuse with
`runner.not-installed` before anything is recorded, naming the runner, its package and its extra. The fix SHALL say to
install `troupe-run[<extra>]` with the command on the install page, or, for a runner with no extra, to reinstall troupe
or run `uv sync` in a checkout of troupe.

#### Scenario: A library-backed runner that isn't installed
- **WHEN** a person performs an actor whose runner, `lm-studio`, is in an extra, and its package isn't installed
- **THEN** it is refused with `runner.not-installed`, with details naming the runner, the package and `lm-studio`,
  and a fix naming `troupe-run[lm-studio]` and the install page
- **AND** nothing is recorded, and no run directory or worktree is made

#### Scenario: A base runner missing from a broken install
- **WHEN** a person performs an actor whose runner is `scripted`, and `troupe_runner_scripted` isn't installed
- **THEN** it is refused with `runner.not-installed`, with no extra in its details, and a fix naming the install page and
  `uv sync`

#### Scenario: Rehearsing
- **WHEN** a person runs `troupe perform <actor> --rehearse` for an actor whose runner isn't installed
- **THEN** it is refused with `runner.not-installed`, as a perform would be

### Requirement: A context event is recorded and shown like every run event
troupe SHALL record a runner's `context` event as it records every run event, with its lineage, in `seq` order. `logs`
SHALL show it with its kind, who lost the content and each amount it carries. It SHALL NOT change the run's outcome.

#### Scenario: A run whose engine compacted
- **WHEN** a runner sends `init`, a `context` event with kind `compacted`, by `engine` and `tokensBefore` 41000, and
  then an `ok` result, and the run exits cleanly with a passing effect check
- **THEN** the run's events hold a `Run.Reported` carrying that `context` event unchanged, with lineage
- **AND** the run's outcome is `succeeded`

#### Scenario: Logs show the loss
- **WHEN** a person reads the logs of that run
- **THEN** the `context` event's line names `compacted`, `engine` and 41000 tokens before

#### Scenario: An oversized context event
- **WHEN** a runner sends a `context` event larger than the run's maximum event size
- **THEN** troupe records an `oversized` event whose `originalType` is `context`, and keeps the original in the
  artifact store

### Requirement: A run's onContextFull comes from the actor and policy
`perform` SHALL work out each run's `onContextFull` from the actor's `onContextFull` and the `compaction` policy:
under `actors`, the actor's value, `fail` when absent; under `all`, `compact` unless the actor says `fail`; under
`none`, `fail`. It SHALL send that value in `run/start`.

#### Scenario: An actor that opts in
- **WHEN** the policy is `actors` and an actor with `onContextFull` `compact` is performed
- **THEN** its `run/start` has `onContextFull` `compact`

#### Scenario: An actor that says nothing
- **WHEN** the policy is `actors` and an actor without `onContextFull` is performed
- **THEN** its `run/start` has `onContextFull` `fail`

#### Scenario: Policy turns it on
- **WHEN** the policy is `all` and an actor without `onContextFull` is performed
- **THEN** its `run/start` has `onContextFull` `compact`

#### Scenario: An actor that keeps failing under all
- **WHEN** the policy is `all` and an actor with `onContextFull` `fail` is performed
- **THEN** its `run/start` has `onContextFull` `fail`

### Requirement: Policy none refuses an actor that asks to compact
When the `compaction` policy is `none`, `perform` SHALL refuse an actor whose `onContextFull` is `compact` with
`policy.compaction-forbidden`, naming the actor, `TROUPE_POLICY_COMPACTION` and how to fix it, before the run's
start is recorded and before any worktree is made.

#### Scenario: A forbidden opt-in
- **WHEN** `TROUPE_POLICY_COMPACTION` is `none` and an actor with `onContextFull` `compact` is performed
- **THEN** `perform` fails with `policy.compaction-forbidden`, naming the actor and the variable
- **AND** no run is recorded and no runner is started

#### Scenario: An actor that didn't ask
- **WHEN** `TROUPE_POLICY_COMPACTION` is `none` and an actor without `onContextFull` is performed
- **THEN** the run starts, and its `run/start` has `onContextFull` `fail`

### Requirement: A run's start records whether it may compact and why
The run's start SHALL record its `onContextFull` and its source: `actor` when the actor sets `onContextFull`,
otherwise `policy` when the `compaction` policy is `all` or `none`, otherwise `default`.

#### Scenario: Decided by the actor
- **WHEN** the policy is `actors` and an actor with `onContextFull` `compact` is performed
- **THEN** the run's start records `onContextFull` `compact` with source `actor`

#### Scenario: Decided by policy
- **WHEN** the policy is `all` and an actor without `onContextFull` is performed
- **THEN** the run's start records `onContextFull` `compact` with source `policy`

#### Scenario: The default
- **WHEN** the policy is `actors` and an actor without `onContextFull` is performed
- **THEN** the run's start records `onContextFull` `fail` with source `default`
