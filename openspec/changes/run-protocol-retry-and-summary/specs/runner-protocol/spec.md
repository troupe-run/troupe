## ADDED Requirements

### Requirement: A result says when a retry wasn't safe
A runner that ends a run on a failure it would otherwise have retried, because a retry could repeat something the run
had already done, SHALL say so in the `result`'s `notRetried`, from a closed list with one entry: `side-effect`, a
tool call had already been carried out or answered and a retry could carry it out again. Its message SHALL still say what
happened. A runner SHALL NOT add values of its own.

#### Scenario: A lost connection after a tool call
- **WHEN** a runner whose retry starts the run's conversation again loses its connection after a tool call has run
- **THEN** its `result` has status `error`, `reason` `network` and `notRetried` `side-effect`, and it sends no
  `retry` for that failure

#### Scenario: A value off the list
- **WHEN** a runner sends a `result` with status `error`, `reason` `network` and `notRetried` `unsafe`
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation

#### Scenario: Retries that ran out
- **WHEN** a runner retries a request until its attempts run out
- **THEN** its `result` carries the last retry's reason and no `notRetried`

### Requirement: Only a failure a retry can name carries notRetried
A `result` SHALL carry `notRetried` only when its status is `error` and its `reason` is one a `retry` can name:
`authentication`, `rate-limit`, `network`, `server` or `other`. A `result` that breaks this SHALL NOT validate, and
the host SHALL treat it as a protocol violation. Absent, it means the runner retried the failure until its attempts
ran out, or doesn't retry that failure.

#### Scenario: An ok result that says it wasn't retried
- **WHEN** a runner sends a `result` with status `ok` and `notRetried` `side-effect`
- **THEN** it does not validate against the contract's schema

#### Scenario: A reason no retry names
- **WHEN** a runner sends a `result` with status `error`, `reason` `budget` and `notRetried` `side-effect`
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation

#### Scenario: A recorded result keeps the rule
- **WHEN** a `Run.Ended` payload's outcome holds a `result` with status `error`, `reason` `turn-limit` and
  `notRetried` `side-effect`
- **THEN** it does not validate against the topic's payload schema
