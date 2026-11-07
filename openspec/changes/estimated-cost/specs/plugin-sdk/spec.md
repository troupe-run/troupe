## ADDED Requirements

### Requirement: The SDK estimates a cost from usage and a price
The SDK SHALL give runners one estimator that takes a run's usage and `run/start`'s price and returns the estimate in
US dollars, rounded to ten decimal places, or nothing when the contract says an estimate is absent (spec:
runner-protocol). Runners that estimate SHALL use it.

#### Scenario: Every counter priced
- **WHEN** the estimator is given 1,000,000 input, 200,000 cache-read, 100,000 cache-write and 500,000 output tokens,
  and rates of 2, 0.5, 2.5 and 8 dollars per million
- **THEN** it returns 6.35

#### Scenario: No usage
- **WHEN** the estimator is given no usage and a price
- **THEN** it returns nothing

#### Scenario: Agrees with the contract on every input
- **WHEN** the estimator is given generated usages and prices, counters and rates each present or absent
- **THEN** it returns nothing exactly when the contract says an estimate is absent, and otherwise a number of zero or
  more equal to the sum of each counter times its rate over a million
