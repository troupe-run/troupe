# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Version 0 is the draft contract
The contract's version SHALL be 0 until troupe commits to a stable contract, which SHALL be version 1. Version 0 MAY
change in place, with no compatibility promise and no new version number.

#### Scenario: troupe offers the draft
- **WHEN** troupe sends `initialize`
- **THEN** the versions it offers are `[0]`

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
