# Spec Delta

## MODIFIED Requirements

### Requirement: Commands and queries are JSON Schema in the protocol
Every command and query a surface can call SHALL be defined as JSON Schema in `protocol/`: its request, its result
and, when it streams, its updates. troupe's own message types SHALL be checked against those schemas, so the two
can't drift.

#### Scenario: Messages validate against their schemas
- **WHEN** any request, update or result that troupe builds or accepts for `perform`, `status`, `logs`,
  `config-set`, `config-get` or `flush` is serialised
- **THEN** it validates against that message's schema in `protocol/`

#### Scenario: Generated messages agree with the types
- **WHEN** messages generated at random from the schemas are parsed by troupe and serialised again
- **THEN** each is accepted, and comes back unchanged

### Requirement: Surfaces reach the core only through the protocol's messages
A surface SHALL call the core by sending a request as data and receiving updates and a result as data. The CLI SHALL
reach `perform`, `status`, `logs`, `config-set`, `config-get` and `flush` only this way, in process.

#### Scenario: The CLI goes through the messages
- **WHEN** the CLI runs `perform`, `status`, `logs`, `config set`, `config unset`, `config get` or `flush`
- **THEN** the core receives a request that validates against that method's request schema
- **AND** what the CLI shows is rendered from updates and a result that validate against their schemas

### Requirement: A request can't widen what troupe does
A request SHALL NOT carry a host path, a command line, or a policy value. Paths in a request SHALL be relative to the
theatre, with `/`, and SHALL NOT leave it. The theatre, who is acting and policy SHALL come from the session the
surface establishes, never from the request.

#### Scenario: An absolute path in a request
- **WHEN** a `config-set` request sets an actor's `expect` to an absolute path, a drive, or a path containing `..`
- **THEN** it is refused, naming the path

#### Scenario: No way to name a program
- **WHEN** the `perform` and `config-set` requests are checked against their schemas
- **THEN** neither has a field that holds a command line or a program to run, and an actor's `runner` is a name from
  troupe's runner table, never a command

## ADDED Requirements

### Requirement: Perform's request names an actor and a direction
A `perform` request SHALL hold the actor's name, an optional direction and an optional `rehearse`, and no runner,
options or effect check.

#### Scenario: An interim field
- **WHEN** a `perform` request holds `runner`
- **THEN** it is refused with `client.invalid-request`, naming the field
