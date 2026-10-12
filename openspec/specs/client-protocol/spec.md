# client-protocol Specification

## Purpose

Defines the commands and queries every surface uses to reach troupe's core: language-neutral messages that the CLI
calls in process today and a run server will serve later, so no behaviour exists in only one surface.

## Requirements

### Requirement: Commands and queries are JSON Schema in the protocol
Every command and query a surface can call SHALL be defined as JSON Schema in `protocol/`: its request, its result
and, when it streams, its updates. troupe's own message types SHALL be checked against those schemas, so the two
can't drift.

#### Scenario: Messages validate against their schemas
- **WHEN** any request, update or result that troupe builds or accepts for `perform`, `status` or `logs` is
  serialised
- **THEN** it validates against that message's schema in `protocol/`

#### Scenario: Generated messages agree with the types
- **WHEN** messages generated at random from the schemas are parsed by troupe and serialised again
- **THEN** each is accepted, and comes back unchanged

### Requirement: Surfaces reach the core only through the protocol's messages
A surface SHALL call the core by sending a request as data and receiving updates and a result as data. The CLI SHALL
reach `perform`, `status` and `logs` only this way, in process.

#### Scenario: The CLI goes through the messages
- **WHEN** the CLI runs `perform`, `status` or `logs`
- **THEN** the core receives a request that validates against that method's request schema
- **AND** what the CLI shows is rendered from updates and a result that validate against their schemas

### Requirement: Requests are read strictly
A request with an unknown method, an unknown field, a missing field, a value of the wrong type, or a value outside
its pattern or range SHALL be refused, naming the method or field and what was wrong. Nothing in a request SHALL be
replaced by a default except an absent optional field.

#### Scenario: An unknown field
- **WHEN** a `status` request has a field its schema doesn't define
- **THEN** it is refused with `client.invalid-request`, naming the field

#### Scenario: An unknown method
- **WHEN** a surface calls a method the protocol doesn't define
- **THEN** it is refused with `client.unknown-method`, naming the method

### Requirement: A request can't widen what troupe does
A request SHALL NOT carry a host path, a command line, or a policy value. Paths in a request SHALL be relative to the
theatre, with `/`, and SHALL NOT leave it. The theatre, who is acting and policy SHALL come from the session the
surface establishes, never from the request.

#### Scenario: An absolute path in a request
- **WHEN** a `perform` request's effect check names an absolute path, a drive, or a path containing `..`
- **THEN** it is refused with `client.invalid-request`, naming the path

#### Scenario: No way to name a program
- **WHEN** a `perform` request is checked against its schema
- **THEN** the schema has no field that holds a command line or a program to run

### Requirement: Long-running calls report progress as updates
A command or query that takes time SHALL send updates as things happen, before its result, so no surface waits
silently. Notices SHALL be sent as updates in the shared notice shape.

#### Scenario: Perform's updates
- **WHEN** a `perform` call runs
- **THEN** the surface receives a `started` update with the run id before any event update
- **AND** an update for each run event as it is recorded, in `seq` order
- **AND** an update for each notice, such as a silence or a retry

### Requirement: Failures are structured errors
A call that can't complete SHALL fail with an error in the protocol's error shape. A run that ends badly SHALL NOT be
a failed call: its outcome and error are part of `perform`'s result.

#### Scenario: A failed run is a result
- **WHEN** a `perform` call runs an actor whose run ends `failed`
- **THEN** the call returns a result whose run has outcome `failed` and the run's error

#### Scenario: A refused command is an error
- **WHEN** a `perform` call is refused before the run starts
- **THEN** the call fails with an error that validates against the protocol's error schema
