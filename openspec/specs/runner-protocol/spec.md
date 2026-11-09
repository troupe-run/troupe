# runner-protocol Specification

## Purpose

Capability: `cap:actor-runners`, `cap:protocol`

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
The `run/start` request SHALL carry the run id (a UUID in canonical lowercase form), the run's direction (what the
actor is asked to do), the actor's character (who it is) when it has one, the workspace directory, the actor's
declared effects, the run's scratch directory, the runner-specific options as an object, and the limits the runner
must respect, including the maximum size of one event.

#### Scenario: Run start is accepted
- **WHEN** the runner receives a valid `run/start`
- **THEN** it answers with a result acknowledging the run id before it sends any run event

#### Scenario: Run id is not a UUID
- **WHEN** a `run/start` carries a run id that is not a canonical lowercase UUID
- **THEN** it does not validate against the contract's schema

#### Scenario: An actor with no character
- **WHEN** troupe starts a run for an actor that has no character
- **THEN** the `run/start` has no `character` field, rather than a null or an empty string

#### Scenario: Direction and character stay apart
- **WHEN** troupe starts a run for an actor with a character, with a direction
- **THEN** the `run/start` carries each in its own field, unchanged

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

### Requirement: The runner takes direction, character and configuration only from its run start
The runner SHALL use no other source of direction, character or configuration from troupe than the `run/start`
request, apart from the runtime's credential, which it SHALL take only from its environment.

#### Scenario: Nothing reaches the runner outside its run start
- **WHEN** troupe starts a runner for an actor with a character, with a direction and runner-specific options
- **THEN** neither the runner's command line nor its environment holds the direction, the character or any of the
  options' values

#### Scenario: The credential is the one exception
- **WHEN** troupe starts a runner for an actor on a runtime with a credential
- **THEN** its environment holds `TROUPE_RUNTIME_CREDENTIAL`, and its command line holds no part of the runtime

### Requirement: Run start options are an extension point
The contract's schema SHALL mark the `run/start` options as an extension point that the runner's published options
schema fills.

#### Scenario: The contract alone accepts only empty options
- **WHEN** a `run/start` is validated against the contract alone, with no runner's options schema bound
- **THEN** it validates with empty options, and does not validate with any option set

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
When the actor's engine retries (for example, an API call), or the runner retries a request to its engine itself,
the runner SHALL send a `retry` event carrying the attempt, the maximum attempts when known, the delay before the next
attempt, and a reason from a fixed list: `authentication`, `rate-limit`, `network`, `server` or `other`.

#### Scenario: Authentication retry
- **WHEN** the engine retries because authentication failed
- **THEN** the runner sends a `retry` event with reason `authentication`

#### Scenario: A runner's own retry
- **WHEN** a runner that calls its engine's API itself makes a request again because the connection dropped
- **THEN** it sends a `retry` event with reason `network` before the new attempt

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

#### Scenario: A reported cost and an estimate together
- **WHEN** a `result` event carries both `costUsd` and `estimatedCostUsd`
- **THEN** it does not validate against the contract's schema

### Requirement: Usage's input counters add up to the whole input
A `result` event's `inputTokens` SHALL count the input tokens not counted in `cacheReadTokens` or `cacheWriteTokens`,
so that the three add up to the run's whole input as the engine reported it. A runner SHALL subtract from its engine's
input count whatever that count includes of the cache's reads and writes. The contract's schema SHALL say this in the
descriptions of `usage` and its counters.

#### Scenario: An engine whose input count leaves the cache out
- **WHEN** an engine reports 6 input tokens, 42158 read from its cache and 5737 written to it, its input count not
  including either
- **THEN** the runner's `result` usage is `inputTokens` 6, `cacheReadTokens` 42158 and `cacheWriteTokens` 5737

#### Scenario: An engine whose input count includes the cache
- **WHEN** an engine reports 300 input tokens, of which 100 were read from its cache and 50 written to it
- **THEN** the runner's `result` usage is `inputTokens` 150, `cacheReadTokens` 100 and `cacheWriteTokens` 50

#### Scenario: The schema states the meaning
- **WHEN** a runner's author reads `usage` in the contract's `run-event.schema.json`
- **THEN** `inputTokens`' description says it leaves out the tokens counted in `cacheReadTokens` and
  `cacheWriteTokens`, and `usage`'s description says the three add up to the whole input

### Requirement: A cache counter left out was not reported
A runner SHALL leave out a cache counter it can't report, and SHALL NOT estimate one. Input its engine counted that the
runner can't separate into a cache counter SHALL stay in `inputTokens`.

#### Scenario: Cache writes reported for only some requests
- **WHEN** a run's engine counts cache reads and writes within its input count, reports 100 cache reads over the run,
  reports cache writes for only some of its requests, and counts 300 input tokens in all
- **THEN** the runner's `result` usage is `inputTokens` 200 and `cacheReadTokens` 100, with no `cacheWriteTokens`

#### Scenario: An engine that reports nothing about its cache
- **WHEN** an engine reports 420 input tokens and nothing about a cache
- **THEN** the runner's `result` usage is `inputTokens` 420, with neither cache counter

### Requirement: The native transcript is a separate stream
The runner SHALL send its engine's native output, record by record and unchanged, as `run/transcript`
notifications in the order produced. A runner that holds the conversation itself SHALL also send each message it adds
to the conversation, verbatim as it sent it, before the engine's output that follows it, and SHALL NOT send re-sent
history again. Transcript records SHALL NOT be interpreted by the host, apart from masking the
run's credential (spec: runs).

#### Scenario: Native records are kept verbatim
- **WHEN** a runner that doesn't use kinds sends transcript records, in a run with no credential or whose records
  don't hold it
- **THEN** the stored transcript contains exactly those records, in that order, byte for byte

#### Scenario: A runner with its own tool loop
- **WHEN** a runner that runs the tool loop itself sends a tool's output back to its engine
- **THEN** the message holding that output is a transcript record, before the engine's next output

#### Scenario: History sent again
- **WHEN** a runner sends its engine the whole conversation with each request
- **THEN** each message appears in the transcript once

#### Scenario: A record that holds the credential
- **WHEN** a runner sends a transcript record that holds the run's credential
- **THEN** the stored record is the same bytes with the credential masked

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

### Requirement: Run start's effects are always explicit
`run/start`'s `effects` SHALL be an object holding all three of `write`, `delete` and `move`, each a list of
workspace-relative patterns, so a read-only actor is sent three empty lists and a runner never has to guess. A
pattern the contract's pattern doesn't accept SHALL make the `run/start` invalid.

#### Scenario: A read-only actor
- **WHEN** troupe starts a run for an actor with no `effects`
- **THEN** the `run/start`'s `effects` is `{"write": [], "delete": [], "move": []}`

#### Scenario: Effects with a list missing
- **WHEN** a `run/start`'s `effects` holds only `write`
- **THEN** it does not validate against the contract's schema

### Requirement: Run start names the run's scratch directory
`run/start`'s `scratch` SHALL be the absolute path of an empty directory, outside the workspace, that the runner and
its engine may use for anything during the run. It SHALL NOT be the workspace or inside it.

#### Scenario: Scratch beside the workspace
- **WHEN** troupe starts a run
- **THEN** its `run/start` carries a `scratch` path that exists, is empty, and is neither the workspace nor inside it

### Requirement: Init says how the runner applies the effects
The `init` event SHALL carry `effects`: `checked` when the runner checks each change its engine asks for against the
declaration before carrying it out, or `translated` when it translates the declaration into its engine's own rules. A
runner that can do neither SHALL NOT conform.

#### Scenario: The scripted runner's init
- **WHEN** the scripted runner starts a run
- **THEN** its `init` event's `effects` is `checked`

#### Scenario: An init without it
- **WHEN** a runner's `init` event has no `effects`
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation

### Requirement: A runner refuses a platform it can't run on
A runner that finds, before it acknowledges `run/start`, that what it runs on doesn't meet a requirement of its own
SHALL refuse `run/start` with the contract's `runner.requirement-unmet`. Its details SHALL name the requirement and
what's wanted, and what was found when the runner could find it.

#### Scenario: An engine too old
- **WHEN** a runner that needs its engine at version 0.12.6 or later finds version 0.12.5
- **THEN** it refuses `run/start` with `runner.requirement-unmet`, whose details name the engine, `>= 0.12.6` and
  `0.12.5`, and the error validates against the contract alone

#### Scenario: Nothing found
- **WHEN** a runner can't find out what it requires, such as a version its engine didn't report
- **THEN** its `runner.requirement-unmet` details have no `found`

### Requirement: Run start carries the run's runtime
When an actor names a runtime, `run/start` SHALL carry `runtime`: its `name`, `endpoint` and `model` as troupe
resolved them, `credential`, `true` when the runner's environment holds the credential and `false` when the
runtime has none, and `price` when troupe has a price for the run's model (spec: runtimes). It SHALL NOT carry the
credential's value or its variable's name. Without a runtime it is absent.

#### Scenario: A runtime with a credential
- **WHEN** troupe starts a run on the runtime `openai` with the model `gpt-test`, and config has no price for it
- **THEN** `run/start` carries `runtime` with `name` `openai`, the endpoint, `model` `gpt-test` and `credential`
  `true`, and nothing else

#### Scenario: A runtime with a price for the run's model
- **WHEN** troupe starts a run on the runtime `openai` with the model `gpt-test`, and config prices `gpt-test` at 2
  dollars per million input tokens and 8 per million output tokens
- **THEN** `run/start`'s `runtime` carries `price` `{"input": 2, "output": 8}`

#### Scenario: No runtime
- **WHEN** troupe starts a run for an actor that names no runtime
- **THEN** `run/start` has no `runtime` field, rather than a null

#### Scenario: The value isn't in run start
- **WHEN** a `run/start` with a `runtime` is validated against the contract's schema
- **THEN** the schema has no field for a credential's value or its variable's name

### Requirement: The credential's value is in the runner's environment as TROUPE_RUNTIME_CREDENTIAL
When `run/start`'s `runtime.credential` is `true`, the runner's environment SHALL hold the credential's value as
`TROUPE_RUNTIME_CREDENTIAL`, and SHALL NOT hold it otherwise. The runner SHALL send it only to the runtime's endpoint,
and SHALL NOT put it in a run event, a transcript record, its standard error or an error.

#### Scenario: The runner finds the key
- **WHEN** troupe starts a run whose `runtime.credential` is `true`
- **THEN** the runner's environment holds `TROUPE_RUNTIME_CREDENTIAL`, and not the variable the runtime's config names

#### Scenario: No credential
- **WHEN** troupe starts a run on `ollama`
- **THEN** the runner's environment has no `TROUPE_RUNTIME_CREDENTIAL`

### Requirement: A reported cost is what the engine reports
A `result`'s `costUsd` SHALL be what the run cost in US dollars as the engine or its service reported it, and SHALL
be absent when it reported none. A runner SHALL NOT put a cost it worked out itself in `costUsd`.

#### Scenario: An engine that reports a cost
- **WHEN** a runner's engine reports that the run cost 0.42 dollars
- **THEN** the `result` carries `costUsd` 0.42 and no `estimatedCostUsd`

### Requirement: An estimated cost is worked out from troupe's price, and marked as one
When the engine reports no cost and `run/start` carries a price, a runner MAY send `estimatedCostUsd`: the run's
usage at that price, in US dollars. It SHALL NOT estimate from a price of its own, or send an estimate without
`run/start`'s price.

#### Scenario: An engine that reports tokens and no price
- **WHEN** a runner's engine reports 1,000,000 input and 500,000 output tokens and no cost, and `run/start`'s price
  is 2 dollars per million input tokens and 8 per million output tokens
- **THEN** the runner's `result` carries `estimatedCostUsd` 6 and no `costUsd`

#### Scenario: No price in run start
- **WHEN** a runner's engine reports no cost and `run/start` carries no price
- **THEN** the `result` carries neither `costUsd` nor `estimatedCostUsd`

### Requirement: A price is in US dollars per million tokens
A price SHALL give US dollars per million tokens for `input` and `output`, each required, and optionally
`cacheRead` and `cacheWrite`, each a number of zero or more. It SHALL hold no other field.

#### Scenario: A price without an output rate
- **WHEN** a `run/start`'s `runtime.price` is `{"input": 2}`
- **THEN** it does not validate against the contract's schema

#### Scenario: A negative rate
- **WHEN** a price's `cacheRead` is `-1`
- **THEN** it does not validate against the contract's schema

### Requirement: An estimate covers every token the run used, or is absent
An estimate SHALL be absent when the usage has no `inputTokens` or `outputTokens`, when a counter the price has a
rate for wasn't reported, or when a counter the price has no rate for holds tokens. It SHALL NOT price one kind of
token at another kind's rate.

#### Scenario: Cache reads with no cache-read rate
- **WHEN** a run's usage has 100 `cacheReadTokens` and its price has no `cacheRead`
- **THEN** the `result` has no `estimatedCostUsd`

#### Scenario: A rate for a counter the engine didn't report
- **WHEN** a run's price has a `cacheWrite` rate and its usage has no `cacheWriteTokens`
- **THEN** the `result` has no `estimatedCostUsd`

#### Scenario: A counter at zero with no rate
- **WHEN** a run's usage has `cacheWriteTokens` 0 and its price has no `cacheWrite`
- **THEN** the estimate is worked out from the other counters

### Requirement: The host drops an estimate it gave no price for
When the run's `run/start` carried no price, the host SHALL record a `result` carrying `estimatedCostUsd` without
it, keep the run's own outcome, and raise the notice `run.estimate-dropped`, naming the runner and saying troupe
gave it no price.

#### Scenario: An estimate with no price given
- **WHEN** a runner whose `run/start` had no `runtime.price` sends an ok `result` with `estimatedCostUsd`
- **THEN** the recorded `result` has no `estimatedCostUsd`, the run succeeds, and a `run.estimate-dropped` notice
  names the runner

#### Scenario: An estimate with a price given
- **WHEN** a runner whose `run/start` carried a price sends a `result` with `estimatedCostUsd`
- **THEN** the host records the `result` as sent, and raises no notice

#### Scenario: An oversized result with an estimate and no price given
- **WHEN** a runner whose `run/start` had no `runtime.price` sends a `result` with `estimatedCostUsd` that is over
  the run's event size
- **THEN** the host stores the result without `estimatedCostUsd`, and the `oversized` event's `ref` holds that result,
  not the line the runner sent

### Requirement: A transcript record can say what kind it is
`run/transcript` SHALL accept an optional `kind`: `sent` for what the runner sent its engine, verbatim; `received`
for what the engine sent back, verbatim; `note` for the runner's own record about the exchange. A record without a
kind is unlabelled: the engine's native output, or a runner's own record when it wasn't offered `transcript-kinds`.
Any other kind SHALL NOT validate against the contract's schema.

#### Scenario: A request body
- **WHEN** a runner that drives an API sends the body of a request it made as a transcript record
- **THEN** the record's kind is `sent` and the record is the body as sent

#### Scenario: An unknown kind
- **WHEN** a `run/transcript` notification carries kind `request`
- **THEN** it does not validate against the contract's schema

### Requirement: The transcript-kinds capability
The host SHALL offer the capability `transcript-kinds` at `initialize`. Capability names SHALL be a closed list in the
contract's schema, and `transcript-kinds` is its only entry. A runner MAY accept it; a runner that has nothing to
label, such as one that passes on an engine's native output, SHALL NOT.

#### Scenario: troupe's offer
- **WHEN** troupe sends `initialize`
- **THEN** its capabilities are `transcript-kinds`

#### Scenario: An unknown capability name
- **WHEN** an `initialize` answer names the capability `widgets`
- **THEN** it does not validate against the contract's schema

### Requirement: Kinds are all or nothing in a run
A runner that accepted `transcript-kinds` SHALL give every transcript record of its run a kind, and one that didn't
SHALL give none. The host SHALL treat a record that breaks this as a protocol violation and store nothing for it.

#### Scenario: A record without a kind in a run that uses kinds
- **WHEN** a runner that accepted `transcript-kinds` sends a transcript record with no kind
- **THEN** the host treats it as a protocol violation, and the record isn't stored

#### Scenario: A kind in a run that doesn't use kinds
- **WHEN** a runner that didn't accept `transcript-kinds` sends a transcript record with kind `received`
- **THEN** the host treats it as a protocol violation, and the record isn't stored

### Requirement: A runner offered no kinds sends its records without them
A runner that would label its records, offered no `transcript-kinds` (a host from before the capability), SHALL send
the same records, in the same order, without a kind.

#### Scenario: An older host
- **WHEN** a runner that uses kinds is offered no capabilities
- **THEN** it answers with no capabilities, and its transcript records are the same records without a kind
