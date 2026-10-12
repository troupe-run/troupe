# Spec Delta

## Purpose

How troupe runs an actor through an out-of-process runner: launching it, supervising the run within named limits,
cancelling it, and deriving one trustworthy outcome per run.

## ADDED Requirements

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

### Requirement: The outcome never comes from the exit code
The host SHALL derive the outcome from the event stream, how the runner ended, and the effect check. The runner's
exit code SHALL be recorded but SHALL NOT decide the outcome.

#### Scenario: Error result with exit code 0
- **WHEN** a runner sends a `result` with status `error` and exits with code 0
- **THEN** the outcome is `failed`

#### Scenario: Success result with a non-zero exit code
- **WHEN** a runner sends a `result` with status `ok`, the effect check passes, and the runner exits non-zero
- **THEN** the outcome is `succeeded` and the exit code is recorded with it

### Requirement: Success needs an ok result and a passing effect check
The outcome SHALL be `succeeded` only when the run's `result` event has status `ok` and the run's effect check
passes. A run with no effect to check SHALL use a check that always passes, stated explicitly by the caller.

#### Scenario: Result ok but declared output missing
- **WHEN** a runner reports status `ok` but a file the run was expected to produce does not exist
- **THEN** the outcome is `failed` with an error naming the missing path

#### Scenario: Result ok and declared output written
- **WHEN** a runner reports status `ok` and every expected file exists with changed contents
- **THEN** the outcome is `succeeded`

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
When a runner violates the contract (an invalid message, an event out of sequence, an event before `init`, an event
after `result`, or a message over the maximum size), the host SHALL stop the runner and the outcome SHALL be
`crashed` with an error that names the violation.

#### Scenario: Garbage on standard output
- **WHEN** a runner writes a line that is not JSON to standard output
- **THEN** the runner is stopped and the outcome is `crashed` with a protocol error naming the line's position

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
contract: the handshake, `init` first, sequence numbers, the result, cancel, shutdown, and exit on end of input.

#### Scenario: Scripted runner conforms
- **WHEN** the conformance suite runs against the scripted runner
- **THEN** every check passes
