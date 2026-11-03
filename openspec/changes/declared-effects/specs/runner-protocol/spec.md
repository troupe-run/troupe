# Spec Delta

## MODIFIED Requirements

### Requirement: Run start carries everything the runner may use
The `run/start` request SHALL carry the run id (a UUID in canonical lowercase form), the run's direction (what the
actor is asked to do), the actor's character (who it is) when it has one, the workspace directory, the actor's
declared effects, the run's scratch directory, the runner-specific options as an object, and the limits the runner
must respect, including the maximum size of one event.

#### Scenario: Run start is accepted
- **WHEN** the runner receives a valid `run/start`
- **THEN** it answers with a result acknowledging the run id before it sends any run event

#### Scenario: Run id is not a UUID
- **WHEN** a `run/start` carries a run id that is not a canonical lowercase UUID
- **THEN** it does not validate against the contract's schema

#### Scenario: An actor with no character
- **WHEN** troupe starts a run for an actor that has no character
- **THEN** the `run/start` has no `character` field, rather than a null or an empty string

#### Scenario: Direction and character stay apart
- **WHEN** troupe starts a run for an actor with a character, with a direction
- **THEN** the `run/start` carries each in its own field, unchanged

#### Scenario: Runner-specific options are opaque to the host
- **WHEN** `run/start` carries options for the runner
- **THEN** the host passes them through unchanged and, at run time, does not validate them beyond being a JSON
  object; the runner validates them

#### Scenario: Options checked against the runner's schema
- **WHEN** a `run/start` is validated against the contract together with the runner's published options schema
- **THEN** it validates only if its options match that runner's schema

#### Scenario: Runner refuses options it doesn't understand
- **WHEN** a runner receives a `run/start` whose options include a key it does not define
- **THEN** it answers with an error naming the key, rather than ignoring it

## ADDED Requirements

### Requirement: Run start's effects are always explicit
`run/start`'s `effects` SHALL be an object holding all three of `write`, `delete` and `move`, each a list of
workspace-relative patterns, so a read-only actor is sent three empty lists and a runner never has to guess. A
pattern the contract's pattern doesn't accept SHALL make the `run/start` invalid.

#### Scenario: A read-only actor
- **WHEN** troupe starts a run for an actor with no `effects`
- **THEN** the `run/start`'s `effects` is `{"write": [], "delete": [], "move": []}`

#### Scenario: Effects with a list missing
- **WHEN** a `run/start`'s `effects` holds only `write`
- **THEN** it does not validate against the contract's schema

### Requirement: Run start names the run's scratch directory
`run/start`'s `scratch` SHALL be the absolute path of an empty directory, outside the workspace, that the runner and
its engine may use for anything during the run. It SHALL NOT be the workspace or inside it.

#### Scenario: Scratch beside the workspace
- **WHEN** troupe starts a run
- **THEN** its `run/start` carries a `scratch` path that exists, is empty, and is neither the workspace nor inside it

### Requirement: Init says how the runner applies the effects
The `init` event SHALL carry `effects`: `checked` when the runner checks each change its engine asks for against the
declaration before carrying it out, or `translated` when it translates the declaration into its engine's own rules. A
runner that can do neither SHALL NOT conform.

#### Scenario: The scripted runner's init
- **WHEN** the scripted runner starts a run
- **THEN** its `init` event's `effects` is `checked`

#### Scenario: An init without it
- **WHEN** a runner's `init` event has no `effects`
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation
