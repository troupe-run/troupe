## ADDED Requirements

### Requirement: Config drop and keep are protocol commands
`config-drop` and `config-keep` SHALL be commands defined in the client protocol, each with a request and result
schema. Each request SHALL name one change id, and SHALL take `rehearse`. No request SHALL name an event, a segment
or a file.

#### Scenario: A request that names a segment
- **WHEN** a `config-drop` request holds a `segments` field
- **THEN** it is refused with `client.invalid-request`, naming the field

#### Scenario: Results validate
- **WHEN** a `config-drop` or `config-keep` call succeeds or is refused
- **THEN** its result or error validates against the protocol's schema for that call

#### Scenario: The notice validates
- **WHEN** a sweep reports `config.edit-abandoned`
- **THEN** the notice validates against the protocol's notice schema
