## ADDED Requirements

### Requirement: The SDK's result type carries notRetried
The SDK's result event SHALL carry `notRetried`, typed as the contract's closed list. Building or parsing a result
SHALL refuse `notRetried` on an `ok` result, or beside a reason a `retry` can't name, naming the event and
`notRetried`.

#### Scenario: A runner builds an ok result that wasn't retried
- **WHEN** a runner builds the SDK's result event with status `ok` and `notRetried` `side-effect`
- **THEN** the SDK raises an error naming the result event and `notRetried`, and nothing is sent

#### Scenario: The host parses notRetried beside a reason no retry names
- **WHEN** the host parses a `result` event with status `error`, `reason` `budget` and `notRetried` `side-effect`
- **THEN** the SDK raises a protocol error naming the result event and `notRetried`

#### Scenario: The list matches the schema
- **WHEN** a value is added to `run-event.schema.json`'s `notRetried` list and not to the SDK's type
- **THEN** the SDK's tests fail, naming the result type and the value
