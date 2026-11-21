## ADDED Requirements

### Requirement: A run summary carries its result's usage and cost
A run summary SHALL carry `usage` exactly as the run's recorded `result` event carries it, and `cost` with the result's
cost in US dollars as `usd` and its `kind`: `reported` for the result's `costUsd`, `estimated` for its
`estimatedCostUsd`. Each SHALL be left out when the result left it out, and both while no result is recorded.

#### Scenario: A run whose service reported its cost
- **WHEN** `status` reports a run whose result carried `usage` with all four counters and `costUsd` 0.4213
- **THEN** its summary's `usage` holds the same four counters, and its `cost` is `usd` 0.4213, `kind` `reported`

#### Scenario: A run whose cost was estimated
- **WHEN** `status` reports a run whose result carried `usage` and `estimatedCostUsd` 0.0136
- **THEN** its summary's `cost` is `usd` 0.0136, `kind` `estimated`

#### Scenario: A run whose runner reported neither
- **WHEN** `status` reports a run whose result carried no `usage` and no cost
- **THEN** its summary has no `usage` and no `cost`

#### Scenario: Tokens but no cost
- **WHEN** `status` reports a run whose result carried `usage` and no cost
- **THEN** its summary has `usage` and no `cost`

#### Scenario: A counter the runner left out
- **WHEN** `status` reports a run whose result's `usage` had `inputTokens` and `outputTokens` only
- **THEN** its summary's `usage` has those two counters and no cache counter

#### Scenario: A run with no result yet
- **WHEN** `status` reports a run whose `perform` is still alive and whose runner hasn't sent its result
- **THEN** its summary has no `usage` and no `cost`

#### Scenario: A cost of an unknown kind
- **WHEN** a run summary's `cost` has a `kind` other than `reported` or `estimated`, or lacks `usd` or `kind`
- **THEN** it doesn't validate against the client protocol's run schema, and reading it fails, naming `cost`
