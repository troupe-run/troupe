# runner-protocol Specification

## Purpose

The language-neutral contract between troupe and an actor runner, so that a runner can be written in any language
and troupe can run any actor (Claude Code, a local model, a scripted runner) the same way.

## Requirements

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
- **WHEN** the host offers protocol version 0 and the runner supports it
- **THEN** the runner's answer names version 0, the runner's name and version, and its capabilities

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
event. The runner SHALL use no other source of instructions or configuration from troupe. The contract's schema
SHALL mark the options as an extension point that the runner's published options schema fills.

#### Scenario: Run start is accepted
- **WHEN** the runner receives a valid `run/start`
- **THEN** it answers with a result acknowledging the run id before it sends any run event

#### Scenario: Run id is not a UUID
- **WHEN** a `run/start` carries a run id that is not a canonical lowercase UUID
- **THEN** it does not validate against the contract's schema

#### Scenario: Runner-specific options are opaque to the host
- **WHEN** `run/start` carries options for the runner
- **THEN** the host passes them through unchanged and, at run time, does not validate them beyond being a JSON
  object; the runner validates them

#### Scenario: Options checked against the runner's schema
- **WHEN** a `run/start` is validated against the contract together with the runner's published options schema
- **THEN** it validates only if its options match that runner's schema

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
one, and the tools available to the actor.

#### Scenario: Init first
- **WHEN** a run starts
- **THEN** the event with `seq` 0 has type `init`

#### Scenario: Another event before init
- **WHEN** a runner's first run event is not `init`
- **THEN** the host treats it as a protocol violation

#### Scenario: Engine detail on init
- **WHEN** a runner's `init` event carries a field the contract doesn't define, such as `native`
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation

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
message, and where known the number of turns, the duration, token usage and cost. Token usage SHALL be named
counters: input, output, cache-read and cache-write tokens. The runner SHALL set status `error` whenever its engine
reported an error, whatever else the engine reported alongside it.

#### Scenario: Engine reports an error under a success label
- **WHEN** the engine's final record says "success" but also flags an error
- **THEN** the runner's `result` event has status `error`

#### Scenario: No events after the result
- **WHEN** a runner sends any run event after its `result` event
- **THEN** the host treats it as a protocol violation

#### Scenario: An unnamed usage counter
- **WHEN** a `result` event's usage holds a counter other than `inputTokens`, `outputTokens`, `cacheReadTokens` and
  `cacheWriteTokens`
- **THEN** it does not validate against the contract's schema

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
schema (code, problem, fix, and optionally path and details). Its code SHALL be one of the contract's own error
codes, or one the runner publishes with its details schema.

#### Scenario: Invalid run start
- **WHEN** a runner rejects `run/start` because it is invalid
- **THEN** the error's `data` validates against the protocol's error schema and names what was invalid

#### Scenario: A contract error code
- **WHEN** a runner refuses a request it can't parse, an unknown method, an unsupported version, a second
  `run/start` or invalid params
- **THEN** the error's code is the contract's code for that failure, and its details match that code's schema

#### Scenario: A code the runner didn't publish
- **WHEN** a runner's error carries a code that is neither the contract's nor in the runner's published error
  codes
- **THEN** it does not validate against the contract's schema together with the runner's

### Requirement: The contract is not specific to one engine
No required field of the contract SHALL be specific to one engine or vendor. Engine-specific detail SHALL appear
only in the native transcript or in the runner-specific options.

#### Scenario: A runner without a model
- **WHEN** a runner has no model or engine (the scripted runner)
- **THEN** its `init` event is valid without those fields

#### Scenario: Engine records stay in the transcript
- **WHEN** a runner drives an engine that reports records the run events don't model
- **THEN** those records reach troupe only as `run/transcript` records, never inside a run event

### Requirement: A runner publishes schemas for its options and its own error codes
A runner SHALL publish a JSON Schema for its options, and one listing each error code of its own with the schema
of that code's details. Both SHALL pass the protocol's strictness check. A runner with no options SHALL publish a
schema accepting only `{}`.

#### Scenario: The scripted runner's schemas
- **WHEN** the scripted runner's published schemas are checked
- **THEN** they pass the strictness check, its documented options validate against its options schema, and
  options with an unknown key don't

#### Scenario: Options the schema refuses, the runner refuses
- **WHEN** the conformance suite sends a runner options holding a key its published options schema doesn't define
- **THEN** the runner answers `run/start` with an error

### Requirement: A success result matches its method's result schema
A JSON-RPC success response SHALL carry a result that validates against the result schema of one of the
contract's methods: `initialize`, `run/start`, `run/cancel` or `shutdown`.

#### Scenario: A result no method defines
- **WHEN** a runner answers a request with a result object that matches none of the contract's result schemas
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation

### Requirement: Version 0 is the draft contract
The contract's version SHALL be 0 until troupe commits to a stable contract, which SHALL be version 1. Version 0 MAY
change in place, with no compatibility promise and no new version number.

#### Scenario: troupe offers the draft
- **WHEN** troupe sends `initialize`
- **THEN** the versions it offers are `[0]`

### Requirement: An error response's id is null only when the request couldn't be read
A runner's error response SHALL carry the failed request's `id`. Its `id` SHALL be `null` only when the request
couldn't be read, as JSON-RPC 2.0 requires. The contract SHALL mark that `null` as an external constraint.

#### Scenario: A request that can't be parsed
- **WHEN** a runner receives a line that isn't valid JSON
- **THEN** it replies with `runner.parse-error` and `"id": null`, and the reply validates against the contract

#### Scenario: A request that can be read
- **WHEN** a runner refuses a request whose `id` it read
- **THEN** its error response carries that `id`
