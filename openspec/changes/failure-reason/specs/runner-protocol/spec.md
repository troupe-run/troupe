## MODIFIED Requirements

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

#### Scenario: An error result says why
- **WHEN** a runner ends a run with status `error` because its engine refused the credential
- **THEN** the `result` event carries `reason` `authentication` alongside its message

## ADDED Requirements

### Requirement: An error result names one reason from a closed list
A `result` with status `error` SHALL carry a `reason`, one of: `authentication`, `quota`, `rate-limit`, `network`,
`server`, `configuration`, `context-length`, `output-limit`, `refused`, `turn-limit`, `budget`, `cancelled`, `engine`,
`runner` or `other`. A `result` with status `ok` SHALL NOT carry one. A runner's `result` that breaks either rule SHALL
NOT validate, and the host SHALL treat it as a protocol violation.

#### Scenario: An error result without a reason
- **WHEN** a runner sends a `result` with status `error` and no `reason`
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation

#### Scenario: A reason off the list
- **WHEN** a runner sends a `result` with status `error` and `reason` `timeout`
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation

#### Scenario: An ok result with a reason
- **WHEN** a runner sends a `result` with status `ok` and `reason` `budget`
- **THEN** it does not validate against the contract's schema

### Requirement: A failure the list doesn't name is other
A runner whose run fails for a reason the list has no entry for SHALL report `other`, and its message SHALL say what
happened. A runner SHALL NOT add reasons of its own: the list has no extension point.

#### Scenario: A failure without an entry
- **WHEN** a runner's engine ends a response with a status the runner doesn't know
- **THEN** the `result` has status `error`, `reason` `other`, and a message naming that status

#### Scenario: A runner's own reason
- **WHEN** a runner's published schemas try to add a reason to the list
- **THEN** a `result` carrying that reason still does not validate against the contract's schema

### Requirement: Retries that run out end with the last retry's reason
When a runner ends a run because its retries ran out, the `result`'s reason SHALL be the reason of the last `retry`
event it sent, which is one of the four reasons the two lists share: `authentication`, `rate-limit`, `network` or
`server`. A retry whose reason was `other` SHALL end with `other`.

#### Scenario: Server errors until the attempts run out
- **WHEN** a runner retries a request answered 503 until its attempts run out
- **THEN** its last `retry` has reason `server`, and its `result` has status `error` and `reason` `server`

#### Scenario: Retries that changed reason
- **WHEN** a runner's first retry is for a dropped connection and its last for a 429
- **THEN** its `result` has `reason` `rate-limit`

### Requirement: A cancelled run's result says it was cancelled
A runner that sends a final `result` after `run/cancel` SHALL give it status `error` and `reason` `cancelled`.

#### Scenario: A result after cancel
- **WHEN** the host cancels a run and the runner sends a final `result`
- **THEN** the `result` has status `error` and `reason` `cancelled`

### Requirement: A recorded result keeps the same rule
troupe SHALL hold the results it records and reads back to the same rule as the ones a runner sends: an `error` result
without a `reason`, a reason off the list, or a reason on an `ok` result SHALL be refused as a malformed record.

#### Scenario: A recorded error result without a reason
- **WHEN** troupe reads a run's events and its `Run.Ended` outcome holds an `error` result with no `reason`
- **THEN** it refuses the record as malformed, naming the result and `reason`
