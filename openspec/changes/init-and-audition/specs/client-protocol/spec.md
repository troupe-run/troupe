# Spec Delta

## ADDED Requirements

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
direction. Each surface SHALL phrase the steps for its own users.

#### Scenario: The steps as data
- **WHEN** an `init` request with an audition succeeds in a session whose policy doesn't allow the local stage
- **THEN** its result's steps are a commit of `.troupe`, a local-stage allowance naming the policy setting, and a
  perform naming `lead` and a direction, in that order

#### Scenario: Plain init has no steps to perform
- **WHEN** an `init` request with no audition succeeds
- **THEN** its result lists no perform step
