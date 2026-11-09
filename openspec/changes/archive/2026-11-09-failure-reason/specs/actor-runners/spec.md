## ADDED Requirements

### Requirement: A failed result's reason reaches the outcome
When a run is `failed` with `run.error-result`, the error's details SHALL carry the result's `reason` alongside its
message, and its fix SHALL say what to do for that reason, from one table in core with an entry for every reason on
the list.

#### Scenario: A refused credential
- **WHEN** a runner sends a `result` with status `error` and `reason` `authentication`
- **THEN** the outcome is `failed` with `run.error-result`, its details hold `reason` `authentication` and the
  message, and its fix says to check the credential the actor's runtime names

#### Scenario: A spent budget
- **WHEN** a runner sends a `result` with status `error` and `reason` `budget`
- **THEN** the outcome's details hold `reason` `budget`, and its fix says to raise the budget in the actor's runner
  options or give the actor a smaller task

#### Scenario: Every reason has a fix
- **WHEN** an outcome is derived for an `error` result with each reason on the list in turn
- **THEN** each outcome's error validates against the protocol's error schema, and carries a fix written for that
  reason rather than the generic one

### Requirement: A failed result's reason is shown on every surface
The reason SHALL reach every surface through the outcome's error, with no surface working it out for itself: `perform`,
`status` and `logs` SHALL show the error's problem and fix as they do for any other outcome, and the problem SHALL name
the reason.

#### Scenario: perform shows why
- **WHEN** `troupe perform` runs an actor whose runner ends with `reason` `turn-limit`
- **THEN** the CLI's error says the run reached its turn limit and how to raise it, and exits with the failure code
