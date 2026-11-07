## ADDED Requirements

### Requirement: A script's error result names its reason
A script's `event` step that sends an `error` result SHALL name its reason, so tests can drive every reason on the
list. The scripted runner's own failures SHALL carry a reason too: a cancel honoured with a result `cancelled`, and a
check a step makes that fails (the character, the runtime, the credential, a tool step's expected error) `other`.

#### Scenario: A scripted error result
- **WHEN** a script's `event` step sends a `result` with status `error` and `reason` `quota`
- **THEN** the runner sends that `result`, with `reason` `quota`

#### Scenario: A scripted error result without a reason
- **WHEN** a script's `event` step sends a `result` with status `error` and no `reason`
- **THEN** the script doesn't validate against the scripted runner's options schema, and the run is refused before it
  starts with `scripted.invalid-script`, naming `reason`

#### Scenario: A cancel honoured with a result
- **WHEN** a script sets the cancel behaviour to honour with a result, and the host cancels the run
- **THEN** the runner's `result` has status `error` and `reason` `cancelled`

#### Scenario: A character check that fails
- **WHEN** a script's character check finds a character it didn't expect
- **THEN** the runner's `result` has status `error` and `reason` `other`, and its message names both characters
