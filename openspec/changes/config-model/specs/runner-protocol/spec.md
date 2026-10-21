# Spec Delta

## MODIFIED Requirements

### Requirement: Run start carries everything the runner may use
The `run/start` request SHALL carry the run id (a UUID in canonical lowercase form), the run's direction (what the
actor is asked to do), the actor's character (who it is) when it has one, the workspace directory, the
runner-specific options as an object, and the limits the runner must respect, including the maximum size of one
event. The runner SHALL use no other source of direction, character or configuration from troupe. The contract's
schema SHALL mark the options as an extension point that the runner's published options schema fills.

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
