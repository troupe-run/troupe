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
fail, `runner.reported` when the runner sent no init, and a worktree workspace's `clones` until its worktree is
made. It SHALL carry `workspace` always, and `changes` exactly when the workspace is a worktree. No field of a summary
SHALL be `null`.

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

#### Scenario: A worktree not made yet
- **WHEN** `status` reports a worktree run whose start is recorded and whose worktree isn't made yet
- **THEN** its summary's workspace has its path, base and whether the theatre was dirty, and no `clones`
- **AND** the summary validates against the client protocol's run schema

### Requirement: A run summary names its transcript's format
A run summary SHALL carry `transcriptFormat` exactly when it carries `transcript`, as the run's end recorded it.

#### Scenario: A transcript and its format
- **WHEN** `status` reports an ended run whose runner started
- **THEN** its summary carries `transcript` and `transcriptFormat`, and a summary with one and not the other doesn't
  validate against the client protocol's run schema

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

### Requirement: Init is a protocol command
`init` SHALL be a command in the client protocol, with a request and a result schema. Its request SHALL hold an
optional `audition` (with an optional `runner`) and an optional `rehearse`, and no path: the session says where the
theatre is made. The CLI SHALL reach `init` only through these messages, in process.

#### Scenario: A request that names a path
- **WHEN** an `init` request holds a `path` field
- **THEN** it is refused with `client.invalid-request`, naming the field

#### Scenario: Init's messages validate
- **WHEN** an `init` call succeeds, is rehearsed or is refused
- **THEN** its result or error validates against the protocol's schema for that call

#### Scenario: The CLI goes through the messages for init
- **WHEN** the CLI runs `troupe init --audition --runner scripted`
- **THEN** the core receives an `init` request that validates against its request schema
- **AND** what the CLI prints is rendered from a result that validates against the `init` result schema

### Requirement: Init's result carries its next steps as data
An `init` result for an audition SHALL list its next steps as data, in order: committing the theatre's directory,
allowing the local stage when the session's policy doesn't already, and performing the actor with an example
direction. The perform step SHALL name the `troupe-run` extra its runner comes with, when it has one. Each surface SHALL
phrase the steps for its own users.

#### Scenario: The steps as data
- **WHEN** an `init` request with an audition succeeds in a session whose policy doesn't allow the local stage
- **THEN** its result's steps are a commit of `.troupe`, a local-stage allowance naming the policy setting, and a
  perform naming `lead` and a direction, in that order

#### Scenario: Plain init has no steps to perform
- **WHEN** an `init` request with no audition succeeds
- **THEN** its result lists no perform step

#### Scenario: A runner in an extra
- **WHEN** an `init` request with an audition on the `lm-studio` runner, installed through its extra, succeeds
- **THEN** its perform step's `extra` is `lm-studio`

#### Scenario: A runner in the base install
- **WHEN** an `init` request with an audition on the `scripted` runner succeeds
- **THEN** its perform step has no `extra`

### Requirement: A run summary carries its run's audit
A run summary SHALL carry `audit`, exactly as the run's end recorded it, exactly when the run has ended and its runner
started, that is when its state is `ended` and it carries a `transcript`. It SHALL leave `audit` out for a run that
hasn't ended and for one whose runner never started.

#### Scenario: A failed run's summary
- **WHEN** `status` reports a run that failed after changing `src/a.py` outside its declaration
- **THEN** its summary's `audit.outside` names `src/a.py`, what happened to it and the effect it needed

#### Scenario: A running run's summary
- **WHEN** `status` reports a run whose `perform` is still alive
- **THEN** its summary has no `audit`

#### Scenario: A summary whose audit has both findings and an error
- **WHEN** a run summary's `audit` has both `outside` and `error`
- **THEN** it doesn't validate against the client protocol's run schema

#### Scenario: A summary that leaves out its audit
- **WHEN** a run summary has state `ended` and a `transcript`, and no `audit`
- **THEN** it doesn't validate against the client protocol's run schema, and the SDK refuses to read it, naming
  `audit`

#### Scenario: An audit without a runner that started
- **WHEN** a run summary has state `ended`, no `transcript`, and an `audit`
- **THEN** it doesn't validate against the client protocol's run schema

### Requirement: A run summary carries its run's recorded notices
A run summary SHALL carry `notices`, each recorded notice of the run with the time it was recorded, in recorded
order, whatever the run's state. It SHALL leave `notices` out when the run recorded none, never sending it empty.

#### Scenario: A run that fell silent
- **WHEN** `status` reports a run that recorded one `run.silent` notice
- **THEN** its summary's `notices` holds one entry, with the time it was recorded and the notice's code, problem
  and fix
- **AND** the summary validates against the client protocol's run schema

#### Scenario: A run with no notices
- **WHEN** `status` reports a run that recorded no notice
- **THEN** its summary has no `notices`

#### Scenario: A summary with an empty notices list
- **WHEN** a run summary has `notices` as an empty list
- **THEN** it doesn't validate against the client protocol's run schema

### Requirement: The logs result holds the run's log
The `logs` result SHALL hold `log`, the run's events and recorded notices in recorded order. Each entry SHALL say
its `kind`: `event` for a run event, with its `seq`, or `run-notice` for a recorded notice, with no `seq`. Both SHALL
name the run and the time the entry was recorded. Following's updates SHALL carry the same entries.

#### Scenario: A log with a notice
- **WHEN** a client reads the `logs` result of a run that recorded a `run.retrying` notice after its `retry` event
- **THEN** its `log` holds an entry of kind `event` for the `retry` event, then one of kind `run-notice` holding
  the notice
- **AND** the result validates against the `logs` result schema

#### Scenario: A recorded notice while following
- **WHEN** a client follows a run that records a notice
- **THEN** it receives an update of kind `run-notice`, distinct from the `notice` updates `logs` itself sends

#### Scenario: A logged notice with a seq
- **WHEN** a `logs` result's entry has kind `run-notice` and a `seq`
- **THEN** it doesn't validate against the `logs` result schema

### Requirement: A run summary's recording names what wasn't recorded first
A run summary's `recording` SHALL name exactly one of `failedAt`, the first run event's `seq` that wasn't recorded,
and `notice`, the code of a notice raised for the run that wasn't recorded, whichever failed first, with the error.

#### Scenario: A recording failure on a notice
- **WHEN** `status` reports a run whose end recorded that recording failed at the notice `run.silent`
- **THEN** its summary's `recording` has `notice` `run.silent` and the error, and no `failedAt`

#### Scenario: A recording that names both
- **WHEN** a run summary's `recording` has both `failedAt` and `notice`, or neither
- **THEN** it doesn't validate against the client protocol's run schema

### Requirement: A run summary that hasn't ended carries nothing from the run's end
A run summary whose `state` isn't `ended` SHALL carry no `transcript`, `transcriptFormat`, `stderr`, `error` or
`recording`, since troupe takes each from the run's end. The client protocol's run schema SHALL refuse such a summary,
and reading one SHALL fail, naming the field.

#### Scenario: A running run with a transcript
- **WHEN** a run summary has state `running` and a `transcript` and `transcriptFormat`
- **THEN** it doesn't validate against the client protocol's run schema, and reading it fails, naming `transcript`

#### Scenario: An interrupted run with standard error
- **WHEN** a run summary has state `interrupted` and a `stderr`
- **THEN** it doesn't validate against the client protocol's run schema, and reading it fails, naming `stderr`

#### Scenario: An unfinished run elsewhere with an error or a recording failure
- **WHEN** a run summary has state `unfinished-elsewhere` and an `error`, or a `recording`
- **THEN** it doesn't validate against the client protocol's run schema, and reading it fails, naming the field

#### Scenario: What troupe reports for a run that hasn't ended
- **WHEN** `status` reports a run whose `perform` is still alive
- **THEN** its summary carries none of `transcript`, `transcriptFormat`, `stderr`, `error` and `recording`, and
  validates against the client protocol's run schema
