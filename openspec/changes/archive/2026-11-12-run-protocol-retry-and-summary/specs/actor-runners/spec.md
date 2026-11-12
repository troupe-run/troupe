## ADDED Requirements

### Requirement: A failure that wasn't retried reaches the outcome
When a run is `failed` with `run.error-result` and its result carried `notRetried`, the error's details SHALL carry
it beside the reason, and the fix SHALL say that the runner didn't retry because a tool call had already run, so the
run's changes are to be reviewed before the actor is performed again, as well as the reason's own fix. Every surface
SHALL get it through the outcome's error.

#### Scenario: A lost connection after a tool call
- **WHEN** a runner sends a `result` with status `error`, `reason` `network` and `notRetried` `side-effect`
- **THEN** the outcome is `failed` with `run.error-result`, its details hold `reason` `network` and `notRetried`
  `side-effect`, and its fix says a tool call had already run, to review the run's changes with `troupe diff`, and to
  check the connection

#### Scenario: A failure whose retries ran out
- **WHEN** a runner sends a `result` with status `error` and `reason` `network`, and no `notRetried`
- **THEN** the outcome's details hold no `notRetried`, and its fix is the reason's own

#### Scenario: logs shows it on the result's line
- **WHEN** `troupe logs` shows a `result` event with `reason` `network` and `notRetried` `side-effect`
- **THEN** the event's line names both
