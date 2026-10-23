## MODIFIED Requirements

### Requirement: Run start carries everything the runner may use
The `run/start` request SHALL carry the run id (a UUID in canonical lowercase form), the run's direction (what the
actor is asked to do), the actor's character (who it is) when it has one, the workspace directory, the
runner-specific options as an object, and the limits the runner must respect, including the maximum size of one
event.

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

### Requirement: The runner takes direction, character and configuration only from its run start
The runner SHALL use no other source of direction, character or configuration from troupe than the `run/start`
request.

#### Scenario: Nothing reaches the runner outside its run start
- **WHEN** troupe starts a runner for an actor with a character, with a direction and runner-specific options
- **THEN** neither the runner's command line nor its environment holds the direction, the character or any of the
  options' values

### Requirement: Run start options are an extension point
The contract's schema SHALL mark the `run/start` options as an extension point that the runner's published options
schema fills.

#### Scenario: The contract alone accepts only empty options
- **WHEN** a `run/start` is validated against the contract alone, with no runner's options schema bound
- **THEN** it validates with empty options, and does not validate with any option set
