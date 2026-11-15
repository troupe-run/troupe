## MODIFIED Requirements

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
- **WHEN** an `init` request with an audition on the `example` runner, installed through its extra `example`, succeeds
- **THEN** its perform step's `extra` is `example`

#### Scenario: A runner in the base install
- **WHEN** an `init` request with an audition on the `scripted` runner succeeds
- **THEN** its perform step has no `extra`
