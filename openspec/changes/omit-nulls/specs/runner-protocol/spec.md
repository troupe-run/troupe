# Spec Delta

## ADDED Requirements

### Requirement: An error response's id is null only when the request couldn't be read
A runner's error response SHALL carry the failed request's `id`. Its `id` SHALL be `null` only when the request
couldn't be read, as JSON-RPC 2.0 requires. The contract SHALL mark that `null` as an external constraint.

#### Scenario: A request that can't be parsed
- **WHEN** a runner receives a line that isn't valid JSON
- **THEN** it replies with `runner.parse-error` and `"id": null`, and the reply validates against the contract

#### Scenario: A request that can be read
- **WHEN** a runner refuses a request whose `id` it read
- **THEN** its error response carries that `id`
