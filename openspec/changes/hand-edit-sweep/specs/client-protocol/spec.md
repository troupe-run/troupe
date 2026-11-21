## MODIFIED Requirements

### Requirement: Commands and queries are JSON Schema in the protocol
Every command and query a surface can call SHALL be defined as JSON Schema in `protocol/`: its request, its result
and, when it streams, its updates. troupe's own message types SHALL be checked against those schemas, so the two
can't drift.

#### Scenario: Messages validate against their schemas
- **WHEN** any request, update or result that troupe builds or accepts for `perform`, `status`, `logs`,
  `config-set`, `config-get` or `sync` is serialised
- **THEN** it validates against that message's schema in `protocol/`

#### Scenario: Generated messages agree with the types
- **WHEN** messages generated at random from the schemas are parsed by troupe and serialised again
- **THEN** each is accepted, and comes back unchanged

### Requirement: Surfaces reach the core only through the protocol's messages
A surface SHALL call the core by sending a request as data and receiving updates and a result as data. The CLI SHALL
reach `perform`, `status`, `logs`, `config-set`, `config-get` and `sync` only this way, in process.

#### Scenario: The CLI goes through the messages
- **WHEN** the CLI runs `perform`, `status`, `logs`, `config set`, `config unset`, `config get` or `sync`
- **THEN** the core receives a request that validates against that method's request schema
- **AND** what the CLI shows is rendered from updates and a result that validate against their schemas
