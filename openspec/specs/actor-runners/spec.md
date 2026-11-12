# actor-runners Specification

## Purpose

Capability: `cap:actor-runners`

How troupe runs an actor through an out-of-process runner: launching it, supervising the run within named limits,
cancelling it, and deriving one trustworthy outcome per run.

## Requirements

### Requirement: Every run attempt has exactly one outcome
Every run attempt SHALL end with exactly one outcome: `succeeded`, `failed`, `cancelled`, `timed-out`, `crashed` or
`could-not-start`. Every outcome other than `succeeded` and `cancelled` SHALL carry an error in the protocol's error
shape. The outcome SHALL be returned as data; a failed run SHALL NOT be raised as an exception.

#### Scenario: Each outcome is reachable
- **WHEN** the scripted runner is driven to each outcome in turn
- **THEN** the host reports that outcome, once, for each run

#### Scenario: Outcome errors match the schema
- **WHEN** a run ends with an outcome that carries an error
- **THEN** the error validates against the protocol's error schema

### Requirement: The exit code alone never makes a run succeed
The host SHALL derive the outcome from the event stream, the effect check and how the runner ended, together. The
exit code SHALL be recorded with every outcome. A clean exit SHALL NOT make a run succeed on its own, and a run
without a `result` SHALL NOT succeed whatever its exit code.

#### Scenario: Error result with exit code 0
- **WHEN** a runner sends a `result` with status `error` and exits with code 0
- **THEN** the outcome is `failed`

#### Scenario: No result with exit code 0
- **WHEN** a runner exits with code 0 without sending a `result`, and no cancel was requested
- **THEN** the outcome is `crashed`

### Requirement: Success needs an ok result, a passing effect check and a clean exit
The outcome SHALL be `succeeded` only when the run's `result` event has status `ok`, the run's effect check passes,
and the runner exits with code 0 after `shutdown`. The effect check SHALL pass only when every expected file was
made or changed and the audit of the run's changes against its declared effects passes (spec: effects). With no
expected files, the effect check SHALL still audit the run's changes.

#### Scenario: Result ok but declared output missing
- **WHEN** a runner reports status `ok` but a file the run was expected to produce does not exist
- **THEN** the outcome is `failed` with an error naming the missing path

#### Scenario: Result ok and declared output written
- **WHEN** a runner reports status `ok`, every expected file exists with changed contents, every change is declared,
  and the runner exits 0
- **THEN** the outcome is `succeeded`

#### Scenario: Result ok and a change outside the declaration
- **WHEN** a runner reports status `ok` and exits 0, but the run changed a file its actor didn't declare
- **THEN** the outcome is `failed` with an error naming the file and the effect it needed

#### Scenario: Success result with a non-zero exit code
- **WHEN** a runner reports status `ok`, the effect check passes, and the runner then exits with code 3
- **THEN** the outcome is `failed` with an error saying the runner reported success but exited with code 3, so the
  run's state is uncertain

#### Scenario: Success result, then killed during shutdown
- **WHEN** a runner reports status `ok`, the effect check passes, and the runner does not exit within the grace
  period after `shutdown` and is killed
- **THEN** the outcome is `failed` with the same uncertain-state error

### Requirement: A run without a result did not succeed
When the runner's stream ends without a `result` event, the outcome SHALL be `cancelled` if the host had asked to
cancel, `timed-out` if a run limit had expired, and `crashed` otherwise.

#### Scenario: Runner exits mid-run
- **WHEN** a runner exits with code 0 before sending a `result` and no cancel was requested
- **THEN** the outcome is `crashed`

#### Scenario: Cancelled runner sends no result
- **WHEN** the host cancels a run and the runner exits without a `result`
- **THEN** the outcome is `cancelled`

### Requirement: Protocol violations end the run
When a runner violates the contract, the host SHALL stop the runner and the outcome SHALL be `crashed` with an
error that names the violation. A malformed or ambiguous message SHALL be a violation, never quietly read with a
default. The violations are listed in the scenarios.

#### Scenario: Garbage on standard output
- **WHEN** a runner writes a line that is not JSON to standard output
- **THEN** the runner is stopped and the outcome is `crashed` with a protocol error naming the line's position

#### Scenario: Ambiguous JSON
- **WHEN** a runner sends a message with a duplicated key, or with `NaN` or `Infinity` as a value
- **THEN** it is a protocol violation, not read with either value

#### Scenario: Unknown method or response
- **WHEN** a runner sends a notification with a method the contract doesn't define, or a response to an id the
  host never sent
- **THEN** it is a protocol violation

#### Scenario: Answers that don't match the request
- **WHEN** a runner chooses a protocol version the host didn't offer, answers `run/start` with a different run id,
  or sends an event or transcript record for a different run id
- **THEN** it is a protocol violation

#### Scenario: Tool result without its call
- **WHEN** a runner sends a `tool_result` whose call id matches no earlier `tool_call` in the run
- **THEN** it is a protocol violation

#### Scenario: Invalid base64 transcript record
- **WHEN** a runner sends a transcript record with encoding `base64` that is not valid base64
- **THEN** it is a protocol violation, and nothing is written to the transcript for it

#### Scenario: A served model that is init's
- **WHEN** a runner's `init` names the model `m-1` and it later sends `served_model` with `model` `m-1`
- **THEN** it is a protocol violation naming the model

#### Scenario: A served model reported twice
- **WHEN** a runner sends `served_model` with `model` `m-2` twice in one run
- **THEN** the second is a protocol violation naming the model

### Requirement: Runners start with an explicit environment
The host SHALL start a runner under the runner environment policy, a named default that selects nothing from the
host: the runner gets only the variables the caller names, plus the minimum the operating system needs to start a
process. It SHALL NOT pass through the host's environment.

#### Scenario: Host secret is not inherited
- **WHEN** the host process has an environment variable the caller did not name
- **THEN** the runner does not see that variable

#### Scenario: Named variable is passed
- **WHEN** the caller names an environment variable and its value
- **THEN** the runner sees it

### Requirement: A runner that cannot start is reported
When the runner's command cannot be started, or the handshake fails or does not complete within the start timeout,
the outcome SHALL be `could-not-start` with an error naming the command and the fix.

#### Scenario: Command not found
- **WHEN** the runner command does not exist
- **THEN** the outcome is `could-not-start` and the error names the command

#### Scenario: Runner never answers the handshake
- **WHEN** a runner does not answer `initialize` within the start timeout
- **THEN** the runner is stopped and the outcome is `could-not-start`

### Requirement: Cancelling is graceful, then hard, and always ends
Cancelling a run SHALL first send `run/cancel`. If the runner has not exited when the cancel grace period passes,
the host SHALL kill the runner's whole process tree. Cancelling SHALL always end the run; it SHALL NOT wait
indefinitely.

#### Scenario: Runner honours cancel
- **WHEN** a run is cancelled and the runner exits within the grace period
- **THEN** the outcome is `cancelled` and the runner was not killed

#### Scenario: Runner ignores cancel
- **WHEN** a run is cancelled and the runner keeps running past the grace period
- **THEN** the runner and every process it started are killed
- **AND** the outcome is `cancelled`

### Requirement: A run's ending records how the runner ended
A run's `ending` SHALL be `killed` exactly when the host killed the runner and that kill is what ended it. A runner
that exits by itself SHALL be `exited`, with its own exit code, even when the host had decided to kill it or had
already sent the kill. The host SHALL decide this from how the process ended, not from whether it had seen the
process end before killing it.

#### Scenario: Killed for a violation while still running
- **WHEN** a runner breaks the contract and keeps running, and nothing has asked it to exit
- **THEN** the host kills it and the run's ending is `killed`

#### Scenario: The runner exits before the kill lands
- **WHEN** a runner sends its `result`, the host sends `shutdown`, the runner sends a late event and then answers
  `shutdown` by exiting 0 before the host's kill takes effect
- **THEN** the outcome is `crashed` with the protocol error naming the late event, and the ending is `exited` with
  exit code 0

#### Scenario: An ok result whose runner exits as the grace period ends
- **WHEN** a runner sends an `ok` result, the effect check passes, and the runner exits 0 by itself just as the
  grace period after `shutdown` passes, before the host's kill takes effect
- **THEN** the ending is `exited` with exit code 0 and the outcome is `succeeded`

#### Scenario: Ignoring cancel still ends killed
- **WHEN** a run is cancelled and the runner keeps running past the grace period
- **THEN** the runner is killed and the run's ending is `killed`

### Requirement: Runs have a time limit
A run SHALL be cancelled when it exceeds its run timeout, and its outcome SHALL be `timed-out` unless it produced a
`result` first.

#### Scenario: Run exceeds its timeout
- **WHEN** a run is still going when its run timeout passes
- **THEN** the run is cancelled and the outcome is `timed-out` with an error naming the limit and its value

### Requirement: Silence and retries are announced, never waited out silently
While a run is going, the host SHALL announce when no event has arrived for the silence threshold, and SHALL
announce each `retry` event as it arrives, through a callback the caller supplies. Each announcement SHALL be a
notice in the protocol's notice shape, with a code declared in one place.

#### Scenario: Runner goes quiet
- **WHEN** a runner sends no event for longer than the silence threshold
- **THEN** the host announces that the run has been silent and for how long

#### Scenario: Engine is retrying
- **WHEN** a runner sends a `retry` event
- **THEN** the host announces the attempt and the reason

#### Scenario: Announcements match the notice schema
- **WHEN** the host announces a silence or a retry
- **THEN** the notice validates against the protocol's notice schema and its code is a declared notice code

### Requirement: Authentication retries fail fast
By default, a `retry` event with reason `authentication` SHALL cancel the run, and the outcome SHALL be `failed`
with an error saying authentication failed and how to fix it. A named setting SHALL control this.

#### Scenario: Bad credentials
- **WHEN** a runner reports a retry with reason `authentication`
- **THEN** the run is cancelled at once and the outcome is `failed` with an authentication error

### Requirement: Every limit is a named setting
Each limit the host uses (the start timeout, the run timeout, the cancel grace period, the silence threshold, the
maximum message size, the maximum event size, the maximum transcript size, the maximum standard error kept, and
failing fast on authentication retries) SHALL have its default in one named place and SHALL be overridable by the caller.

#### Scenario: Defaults come from one place
- **WHEN** a run is started without overriding any limit
- **THEN** every limit in effect equals its default from the one named place

#### Scenario: Caller overrides a limit
- **WHEN** a caller starts a run with a shorter run timeout
- **THEN** that run uses the shorter timeout

### Requirement: Oversized events are kept in full, out of line
When a run event is larger than the maximum event size, the host SHALL store the full event in the artifact store
and pass on in its place an event of the same `seq` and `type` that carries the original size and the stored
event's hash. The run SHALL continue.

#### Scenario: Huge tool result summary
- **WHEN** a runner sends a `tool_result` event larger than the maximum event size
- **THEN** the event passed on carries the size and a hash
- **AND** the stored artifact with that hash is the original event, byte for byte

### Requirement: The transcript is stored and referenced by hash
The host SHALL write the run's transcript records, and separately the runner's standard error, to the artifact
store as the run goes, and the outcome SHALL carry the hash of each. This SHALL hold for every outcome after the
runner started, including `cancelled`, `timed-out` and `crashed`.

#### Scenario: Cancelled run keeps its transcript
- **WHEN** a run is cancelled after the runner sent transcript records
- **THEN** the outcome carries the transcript's hash and the stored transcript holds every record received

#### Scenario: Transcript too large
- **WHEN** a run's transcript passes the maximum transcript size
- **THEN** the run is cancelled and the outcome is `failed` with an error naming the limit
- **AND** the transcript received up to that point is stored and referenced

### Requirement: Events reach the caller in order as they arrive
The host SHALL hand each run event to the caller as it arrives, in `seq` order, so that a caller can record or
display the run while it is going.

#### Scenario: Caller sees events live
- **WHEN** a runner sends an event and then waits before sending the next
- **THEN** the caller receives the first event before the second is sent

### Requirement: Any conforming runner can be checked
troupe SHALL provide a conformance suite that runs against any runner command and checks the runner against this
contract: the handshake, `init` first and saying how the runner applies the effects, a run start carrying effects and
a scratch directory, sequence numbers, the result, cancel, shutdown, and exit on end of input.

#### Scenario: Scripted runner conforms
- **WHEN** the conformance suite runs against the scripted runner
- **THEN** every check passes

#### Scenario: A runner that doesn't say how it applies the effects
- **WHEN** the suite runs against a runner whose `init` has no `effects`
- **THEN** the suite fails, naming the `init` event and `effects`

### Requirement: The audit's findings are part of the outcome
The host SHALL run the audit once the runner has ended, for every run whose runner started, including one that
couldn't finish its handshake, and SHALL return the findings with the outcome: the changes outside the declaration,
which may be none, or the error that kept the audit from running. An outcome whose runner never started SHALL have no
audit. The expected files SHALL be checked only for an `ok` result.

#### Scenario: An error result is audited
- **WHEN** a runner writes a file its actor doesn't declare and sends an `error` result
- **THEN** the outcome is `failed` with `run.error-result`, and its audit names the file

#### Scenario: A runner that started but didn't finish its handshake
- **WHEN** a runner writes a file its actor doesn't declare and then never answers the handshake
- **THEN** the outcome is `could-not-start` with `runner.start-timeout`, and its audit names the file

#### Scenario: A runner that couldn't be started
- **WHEN** a runner's command isn't found
- **THEN** the outcome is `could-not-start` with no audit

#### Scenario: An ok result's audit is its effect check's
- **WHEN** a runner sends an `ok` result and exits 0, and the run changed a file its actor didn't declare
- **THEN** the outcome is `failed` with `effects.outside-declared`, and its audit names the same file

### Requirement: A run that uses kinds stores each record with its kind
When the runner accepted `transcript-kinds`, the host SHALL store each transcript line as a JSON object holding the
record's `kind` and its masked `record`, with `encoding` `base64` exactly when the runner sent the record as base64.
Each line SHALL validate against the protocol's stored transcript record schema.

#### Scenario: A sent record and a received record
- **WHEN** a runner that accepted `transcript-kinds` sends a `sent` record `{"model":"m"}` and then a `received`
  record `data: {}`
- **THEN** the stored transcript is two lines, `{"kind":"sent","record":"{\"model\":\"m\"}"}` and
  `{"kind":"received","record":"data: {}"}`, each followed by `\n`

#### Scenario: A record that isn't text
- **WHEN** a runner that accepted `transcript-kinds` sends a `received` record with encoding `base64`
- **THEN** its stored line has kind `received`, encoding `base64`, and the base64 of the record's bytes after masking

#### Scenario: The credential in a record that uses kinds
- **WHEN** a runner that accepted `transcript-kinds` sends a record holding the run's credential
- **THEN** the stored line's record holds `[credential]` in its place, and the line is still valid JSON

#### Scenario: An escape that would complete the credential
- **WHEN** the run's credential starts with `n`, and a runner that accepted `transcript-kinds` sends a record holding a
  newline (written `\u000a`) followed by the rest of the credential
- **THEN** the stored line holds that record as base64 of its bytes, and no stored byte holds the credential

### Requirement: A run without kinds is stored as before
When the runner didn't accept `transcript-kinds`, the host SHALL store each record's bytes, after masking, followed by
`\n`, with nothing added.

#### Scenario: A Claude Code run
- **WHEN** the Claude Code runner, which accepts no capability, sends its stream-json lines
- **THEN** the stored transcript is those lines, each followed by `\n`, byte for byte

### Requirement: The transcript limit counts what is stored
The maximum transcript size SHALL be measured against the bytes the host stores, the framing included.

#### Scenario: Framing passes the limit
- **WHEN** a run that uses kinds sends records whose own bytes are under the maximum transcript size but whose stored
  lines pass it
- **THEN** the run is cancelled and the outcome is `failed` with an error naming the limit

### Requirement: A failed result's reason reaches the outcome
When a run is `failed` with `run.error-result`, the error's details SHALL carry the result's `reason` alongside its
message, and its fix SHALL say what to do for that reason, from one table in core with an entry for every reason on
the list.

#### Scenario: A refused credential
- **WHEN** a runner sends a `result` with status `error` and `reason` `authentication`
- **THEN** the outcome is `failed` with `run.error-result`, its details hold `reason` `authentication` and the
  message, and its fix says to check the credential the actor's runtime names

#### Scenario: A spent budget
- **WHEN** a runner sends a `result` with status `error` and `reason` `budget`
- **THEN** the outcome's details hold `reason` `budget`, and its fix says to raise the budget in the actor's runner
  options or give the actor a smaller task

#### Scenario: Every reason has a fix
- **WHEN** an outcome is derived for an `error` result with each reason on the list in turn
- **THEN** each outcome's error validates against the protocol's error schema, and carries a fix written for that
  reason rather than the generic one

### Requirement: A failed result's reason is shown on every surface
The reason SHALL reach every surface through the outcome's error, with no surface working it out for itself: `perform`,
`status` and `logs` SHALL show the error's problem and fix as they do for any other outcome, and the problem SHALL name
the reason.

#### Scenario: perform shows why
- **WHEN** `troupe perform` runs an actor whose runner ends with `reason` `turn-limit`
- **THEN** the CLI's error says the run reached its turn limit and how to raise it, and exits with the failure code

### Requirement: A failure that wasn't retried reaches the outcome
When a run is `failed` with `run.error-result` and its result carried `notRetried`, the error's details SHALL carry
it beside the reason, and the fix SHALL say that the runner didn't retry because a tool call had already run, so the
run's changes are to be reviewed before the actor is performed again, as well as the reason's own fix. Every surface
SHALL get it through the outcome's error.

#### Scenario: A lost connection after a tool call
- **WHEN** a runner sends a `result` with status `error`, `reason` `network` and `notRetried` `side-effect`
- **THEN** the outcome is `failed` with `run.error-result`, its details hold `reason` `network` and `notRetried`
  `side-effect`, and its fix says a tool call had already run, to review the run's changes with `troupe diff`, and to
  check the connection

#### Scenario: A failure whose retries ran out
- **WHEN** a runner sends a `result` with status `error` and `reason` `network`, and no `notRetried`
- **THEN** the outcome's details hold no `notRetried`, and its fix is the reason's own

#### Scenario: logs shows it on the result's line
- **WHEN** `troupe logs` shows a `result` event with `reason` `network` and `notRetried` `side-effect`
- **THEN** the event's line names both
