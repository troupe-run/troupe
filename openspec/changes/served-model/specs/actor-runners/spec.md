## MODIFIED Requirements

### Requirement: Protocol violations end the run
When a runner violates the contract, the host SHALL stop the runner and the outcome SHALL be `crashed` with an
error that names the violation. A malformed or ambiguous message SHALL be a violation, never quietly read with a
default. The violations are listed in the scenarios.

#### Scenario: Garbage on standard output
- **WHEN** a runner writes a line that is not JSON to standard output
- **THEN** the runner is stopped and the outcome is `crashed` with a protocol error naming the line's position

#### Scenario: Ambiguous JSON
- **WHEN** a runner sends a message with a duplicated key, or with `NaN` or `Infinity` as a value
- **THEN** it is a protocol violation, not read with either value

#### Scenario: Unknown method or response
- **WHEN** a runner sends a notification with a method the contract doesn't define, or a response to an id the
  host never sent
- **THEN** it is a protocol violation

#### Scenario: Answers that don't match the request
- **WHEN** a runner chooses a protocol version the host didn't offer, answers `run/start` with a different run id,
  or sends an event or transcript record for a different run id
- **THEN** it is a protocol violation

#### Scenario: Tool result without its call
- **WHEN** a runner sends a `tool_result` whose call id matches no earlier `tool_call` in the run
- **THEN** it is a protocol violation

#### Scenario: Invalid base64 transcript record
- **WHEN** a runner sends a transcript record with encoding `base64` that is not valid base64
- **THEN** it is a protocol violation, and nothing is written to the transcript for it

#### Scenario: A served model that is init's
- **WHEN** a runner's `init` names the model `m-1` and it later sends `served_model` with `model` `m-1`
- **THEN** it is a protocol violation naming the model

#### Scenario: A served model reported twice
- **WHEN** a runner sends `served_model` with `model` `m-2` twice in one run
- **THEN** the second is a protocol violation naming the model
