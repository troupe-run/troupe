# Spec Delta

## Purpose

The language-neutral contract between troupe and an actor runner, so that a runner can be written in any language
and troupe can run any actor (Claude Code, a local model, a scripted runner) the same way.

## ADDED Requirements

### Requirement: The contract is JSON Schema in the protocol directory
Every message of the runner contract SHALL be defined as JSON Schema (draft 2020-12) in `protocol/`. The schema
SHALL be the source of truth; any language's types for the contract SHALL be checked against it.

#### Scenario: Every message the host sends validates
- **WHEN** the host sends any message to a runner during the conformance suite
- **THEN** the message validates against the contract's schema

#### Scenario: Every message the scripted runner sends validates
- **WHEN** the scripted runner sends any message during its tests
- **THEN** the message validates against the contract's schema

### Requirement: JSON-RPC 2.0 over standard input and output, one message per line
The host and runner SHALL exchange JSON-RPC 2.0 messages over the runner's standard input and standard output,
each message a single line of UTF-8 JSON ended by a line feed. Standard output SHALL carry nothing else. A runner
MAY write diagnostics to standard error.

#### Scenario: Non-protocol output on standard output
- **WHEN** a runner writes a line to standard output that is not a valid JSON-RPC 2.0 message
- **THEN** the host treats it as a protocol violation

#### Scenario: A message larger than 64 KiB
- **WHEN** a runner sends a single message larger than 64 KiB and within the maximum message size
- **THEN** the host receives it whole

### Requirement: Handshake before anything else
The host's first message SHALL be an `initialize` request carrying the protocol versions and the capabilities it
supports. The runner SHALL answer with one of the offered versions, its name and version, and the capabilities it
will use, each one the host offered. A runner that supports none of the offered versions SHALL answer with an
error, and the host SHALL NOT start a run.

#### Scenario: Compatible runner
- **WHEN** the host offers protocol version 1 and the runner supports it
- **THEN** the runner's answer names version 1, the runner's name and version, and its capabilities

#### Scenario: Capability the host didn't offer
- **WHEN** a runner's answer names a capability that was not in the host's offer
- **THEN** the host treats it as a protocol violation and starts no run

#### Scenario: Incompatible runner
- **WHEN** the host offers only versions the runner does not support
- **THEN** the runner answers with an error naming the versions it supports
- **AND** no run is started

### Requirement: One run per runner process
After the handshake, the host SHALL send exactly one `run/start` request. A runner process SHALL serve one run and
then exit. A second `run/start` SHALL be answered with an error.

#### Scenario: Second run on the same process
- **WHEN** the host sends `run/start` to a runner that has already started a run
- **THEN** the runner answers with an error and the first run is unaffected

### Requirement: Run start carries everything the runner may use
The `run/start` request SHALL carry the run id (a UUID in canonical lowercase form), the actor's instructions, the workspace directory, the
runner-specific options as an object, and the limits the runner must respect, including the maximum size of one
event. The runner SHALL use no other source of instructions or configuration from troupe.

#### Scenario: Run start is accepted
- **WHEN** the runner receives a valid `run/start`
- **THEN** it answers with a result acknowledging the run id before it sends any run event

#### Scenario: Run id is not a UUID
- **WHEN** a `run/start` carries a run id that is not a canonical lowercase UUID
- **THEN** it does not validate against the contract's schema

#### Scenario: Runner-specific options are opaque to the host
- **WHEN** `run/start` carries options the host does not understand
- **THEN** the host passes them through unchanged and does not validate them beyond being a JSON object

#### Scenario: Runner refuses options it doesn't understand
- **WHEN** a runner receives a `run/start` whose options include a key it does not define
- **THEN** it answers with an error naming the key, rather than ignoring it

### Requirement: Run events are notifications with a sequence number
The runner SHALL report the run as `run/event` notifications. Each event SHALL carry the run id, a `seq` that
starts at 0 and increases by one with each event, and a `type`. The event types SHALL be `init`, `turn`,
`tool_call`, `tool_result`, `retry`, `log` and `result`.

#### Scenario: Events are numbered without gaps
- **WHEN** a runner sends events for a run
- **THEN** their `seq` values are 0, 1, 2 and so on, without gaps or repeats

#### Scenario: Gap in the sequence
- **WHEN** the host receives an event whose `seq` is not one more than the previous event's
- **THEN** the host treats it as a protocol violation

### Requirement: The init event comes first
The first run event SHALL be `init`. It SHALL name the runner, its version, the model or engine where there is
one, and the tools available to the actor, and MAY carry vendor-specific detail under `native`.

#### Scenario: Init first
- **WHEN** a run starts
- **THEN** the event with `seq` 0 has type `init`

#### Scenario: Another event before init
- **WHEN** a runner's first run event is not `init`
- **THEN** the host treats it as a protocol violation

### Requirement: Tool calls and results are summarised and paired
A `tool_call` event SHALL carry a call id, the tool's name and a summary of its input. A `tool_result` event SHALL
carry the same call id, whether the tool reported an error, and a summary of its output with the output's full
size in bytes. Full inputs and outputs belong in the transcript, not in events.

#### Scenario: Result names its call
- **WHEN** a runner reports a tool result
- **THEN** its call id matches an earlier `tool_call` event in the same run

### Requirement: Retries are reported as they happen
When the actor's engine retries (for example, an API call), the runner SHALL send a `retry` event carrying the
attempt, the maximum attempts when known, the delay before the next attempt, and a reason from a fixed list:
`authentication`, `rate-limit`, `network`, `server` or `other`.

#### Scenario: Authentication retry
- **WHEN** the engine retries because authentication failed
- **THEN** the runner sends a `retry` event with reason `authentication`

### Requirement: The result event states what the runner saw
A run that ends on its own SHALL end with exactly one `result` event carrying a status of `ok` or `error`, a
message, and where known the number of turns, the duration, token usage and cost. The runner SHALL set status
`error` whenever its engine reported an error, whatever else the engine reported alongside it.

#### Scenario: Engine reports an error under a success label
- **WHEN** the engine's final record says "success" but also flags an error
- **THEN** the runner's `result` event has status `error`

#### Scenario: No events after the result
- **WHEN** a runner sends any run event after its `result` event
- **THEN** the host treats it as a protocol violation

### Requirement: The native transcript is a separate stream
The runner SHALL send its engine's native output, record by record and unchanged, as `run/transcript`
notifications in the order produced. Transcript records SHALL NOT be interpreted by the host.

#### Scenario: Native records are kept verbatim
- **WHEN** a runner sends transcript records
- **THEN** the stored transcript contains exactly those records, in that order, byte for byte

### Requirement: Cancel is a request the runner acknowledges
The host SHALL be able to send `run/cancel` at any time after `run/start`. The runner SHALL acknowledge it, stop
the actor, and then exit. A runner MAY send a final `result` with status `error` after a cancel, but the host SHALL
NOT require one.

#### Scenario: Runner honours cancel
- **WHEN** the host sends `run/cancel` during a run
- **THEN** the runner acknowledges it and exits

### Requirement: Runners exit when their input closes
A runner SHALL stop its actor and exit when its standard input reaches end of file, so that a runner never outlives
a host that has gone away.

#### Scenario: Host goes away
- **WHEN** the runner's standard input is closed during a run
- **THEN** the runner stops its actor and exits

### Requirement: Shutdown ends a finished run
After the `result` event, the host SHALL send `shutdown`; the runner SHALL answer it and exit.

#### Scenario: Clean shutdown
- **WHEN** the host sends `shutdown` after the result
- **THEN** the runner answers and exits

### Requirement: Failures use the shared error shape
A JSON-RPC error from a runner SHALL carry, in its `data`, an object that validates against the protocol's error
schema (code, problem, fix, and optionally path and details).

#### Scenario: Invalid run start
- **WHEN** a runner rejects `run/start` because it is invalid
- **THEN** the error's `data` validates against the protocol's error schema and names what was invalid

### Requirement: The contract is not specific to one engine
No required field of the contract SHALL be specific to one engine or vendor. Engine-specific detail SHALL appear
only under `native` fields or in the runner-specific options.

#### Scenario: A runner without a model
- **WHEN** a runner has no model or engine (the scripted runner)
- **THEN** its `init` event is valid without those fields
