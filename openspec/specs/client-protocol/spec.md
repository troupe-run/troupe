# client-protocol Specification

## Purpose

Capability: `cap:core-api`, `cap:protocol`

Defines the commands and queries every surface uses to reach troupe's core: language-neutral messages that the CLI
calls in process today and a run server will serve later, so no behaviour exists in only one surface.

## Requirements

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
- **WHEN** a `config-set` request sets an actor's `expect` to an absolute path, a drive, or a path containing `..`
- **THEN** it is refused, naming the path

#### Scenario: No way to name a program
- **WHEN** the `perform` and `config-set` requests are checked against their schemas
- **THEN** neither has a field that holds a command line or a program to run, and an actor's `runner` is a name from
  troupe's runner table, never a command

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

### Requirement: A run summary carries what its state knows
A run summary SHALL carry `outcome` and `endedAt` exactly when its `state` is `ended`. It SHALL leave out `error`
when the outcome has none, `transcript` and `stderr` when the runner never started, `recording` when recording didn't
fail, and `runner.reported` when the runner sent no init. It SHALL carry `workspace` always, and `changes` exactly
when the workspace is a worktree. No field of a summary SHALL be `null`.

#### Scenario: A running run
- **WHEN** `status` reports a run whose `perform` is still alive
- **THEN** its summary has state `running`, and no `outcome` or `endedAt`

#### Scenario: An ended run
- **WHEN** `status` reports a run whose end is recorded
- **THEN** its summary has state `ended`, an `outcome` and an `endedAt`

#### Scenario: A summary that contradicts its state
- **WHEN** a run summary has state `interrupted` and an `outcome`, or state `ended` and no `endedAt`
- **THEN** it doesn't validate against the client protocol's run schema

#### Scenario: A summary with a null
- **WHEN** a client reads a run summary in which any field is `null`
- **THEN** reading it fails, naming the field

#### Scenario: Changes that contradict the workspace
- **WHEN** a run summary has workspace `theatre` and `changes`, or changes `pending` and no diff reference
- **THEN** it doesn't validate against the client protocol's run schema

### Requirement: Perform's request names an actor and a direction
A `perform` request SHALL hold the actor's name, an optional direction and an optional `rehearse`, and no runner,
options or effect check.

#### Scenario: An interim field
- **WHEN** a `perform` request holds `runner`
- **THEN** it is refused with `client.invalid-request`, naming the field

### Requirement: Diff, accept and discard are protocol calls
`diff` SHALL be a query, and `accept` and `discard` commands, each defined in the client protocol with a request and
result schema. Each request SHALL name a run, and `accept` and `discard` requests SHALL take an optional `reason` and
`rehearse`. No request SHALL name a path, a diff or a workspace.

#### Scenario: A request that names a diff
- **WHEN** an `accept` request holds a `diff` field
- **THEN** it is refused with `client.invalid-request`, naming the field

#### Scenario: Results validate
- **WHEN** a `diff`, `accept` or `discard` call succeeds or is refused
- **THEN** its result or error validates against the protocol's schema for that call
