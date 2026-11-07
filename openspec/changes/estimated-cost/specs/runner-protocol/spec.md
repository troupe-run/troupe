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

#### Scenario: A reported cost and an estimate together
- **WHEN** a `result` event carries both `costUsd` and `estimatedCostUsd`
- **THEN** it does not validate against the contract's schema

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

## ADDED Requirements

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

### Requirement: The host refuses an estimate it gave no price for
The host SHALL treat a `result` carrying `estimatedCostUsd` as a protocol violation when the run's `run/start`
carried no price.

#### Scenario: An estimate with no price given
- **WHEN** a runner whose `run/start` had no `runtime.price` sends a `result` with `estimatedCostUsd`
- **THEN** the host treats it as a protocol violation, and the run's outcome says so

#### Scenario: An estimate with a price given
- **WHEN** a runner whose `run/start` carried a price sends a `result` with `estimatedCostUsd`
- **THEN** the host records the `result` as sent
