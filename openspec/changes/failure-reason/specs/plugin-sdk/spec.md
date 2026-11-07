## ADDED Requirements

### Requirement: The SDK's result type carries the reason
The SDK's result event SHALL carry the reason, typed as the contract's closed list. Building or parsing a result SHALL
refuse an `error` result without a reason and an `ok` result with one, naming the event and `reason`.

#### Scenario: A runner builds an error result without a reason
- **WHEN** a runner builds the SDK's result event with status `error` and no reason
- **THEN** the SDK raises an error naming the result event and `reason`, and nothing is sent

#### Scenario: The host parses an error result without a reason
- **WHEN** the host parses a `result` event with status `error` and no reason
- **THEN** the SDK raises a protocol error naming the result event and `reason`

#### Scenario: An ok result with a reason
- **WHEN** a runner builds the SDK's result event with status `ok` and reason `budget`
- **THEN** the SDK raises an error naming the result event and `reason`

#### Scenario: The reason list matches the schema
- **WHEN** a reason is added to `run-event.schema.json`'s list and not to the SDK's type
- **THEN** the SDK's tests fail, naming the result type and the reason
