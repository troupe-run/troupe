## MODIFIED Requirements

### Requirement: Init says how the runner applies the effects
The `init` event SHALL carry `effects`: `checked` when the runner checks each change its engine asks for against the
declaration before carrying it out, or `translated` when it translates the declaration into its engine's own rules. A
runner that can do neither SHALL NOT conform. An `init` without `effects` SHALL NOT validate wherever troupe reads one:
as a runner sends it, and as troupe records it and reads it back.

#### Scenario: The scripted runner's init
- **WHEN** the scripted runner starts a run
- **THEN** its `init` event's `effects` is `checked`

#### Scenario: An init without it
- **WHEN** a runner's `init` event has no `effects`
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation

#### Scenario: A recorded init without it
- **WHEN** a recorded run event, or a logged event in a client message, is an `init` with no `effects`
- **THEN** it doesn't validate against the schema troupe records run events with, and the SDK refuses to read it,
  naming `effects`
