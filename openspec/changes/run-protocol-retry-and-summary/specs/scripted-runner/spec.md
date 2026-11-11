## ADDED Requirements

### Requirement: A script's error result can say it wasn't retried
A script's `event` step that sends an `error` result SHALL be able to name `notRetried`, so tests can drive it. The scripted runner's
options schema SHALL hold it to the contract's rule, so a script that names it on an `ok` result or beside a reason a
`retry` can't name is refused before the run starts.

#### Scenario: A scripted result that wasn't retried
- **WHEN** a script's `event` step sends a `result` with status `error`, `reason` `network` and `notRetried`
  `side-effect`
- **THEN** the runner sends that `result`, with `notRetried` `side-effect`

#### Scenario: A scripted notRetried beside the wrong reason
- **WHEN** a script's `event` step sends a `result` with status `error`, `reason` `quota` and `notRetried`
  `side-effect`
- **THEN** the run is refused before it starts with `scripted.invalid-script`, naming `notRetried`
