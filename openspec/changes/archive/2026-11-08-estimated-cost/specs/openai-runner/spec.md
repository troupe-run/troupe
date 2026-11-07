## MODIFIED Requirements

### Requirement: Cost is reported only as the service reports it
The result's `costUsd` SHALL be the sum of the costs the service reports in its responses' usage, and SHALL be absent
when any response reports none. The runner SHALL put no cost of its own in `costUsd`.

#### Scenario: A service that reports no cost
- **WHEN** every response's usage has token counts and no cost
- **THEN** the result has no `costUsd`

#### Scenario: A service that reports a cost
- **WHEN** two responses' usage report costs of 0.001 and 0.002
- **THEN** the result's `costUsd` is 0.003, and the result has no `estimatedCostUsd`

## ADDED Requirements

### Requirement: Cost is estimated from troupe's price when the service reports none
When the result has no `costUsd` and `run/start`'s runtime carries a price, the result SHALL carry the run's summed
usage at that price as `estimatedCostUsd`, worked out by the plugin SDK's estimator, or none when the estimator
gives none.

#### Scenario: OpenAI with a price
- **WHEN** a run's responses report 260 input, 40 cache-read and 30 output tokens and no cost, and `run/start`'s
  price is 2 dollars per million input tokens, 0.5 per million cache reads and 8 per million output tokens
- **THEN** the result's `estimatedCostUsd` is 0.00078, and it has no `costUsd`

#### Scenario: OpenAI without a price
- **WHEN** a run's responses report token counts and no cost, and `run/start` carries no price
- **THEN** the result has neither `costUsd` nor `estimatedCostUsd`

#### Scenario: Cache reads the price doesn't cover
- **WHEN** a run's usage has cache-read tokens and `run/start`'s price has no `cacheRead`
- **THEN** the result has no `estimatedCostUsd`

#### Scenario: No usage reported
- **WHEN** a response completes without usage, and `run/start` carries a price
- **THEN** the result has no `estimatedCostUsd`
