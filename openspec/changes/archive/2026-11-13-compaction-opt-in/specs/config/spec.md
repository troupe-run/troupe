## ADDED Requirements

### Requirement: An actor says what its runs do when the context fills
An actor MAY have `onContextFull`: `fail` or `compact`. `fail`, the default when it's absent, ends a run whose
engine's context fills. `compact` lets the run compact its conversation and carry on. Any other value SHALL be refused
when it's set, naming the path and the accepted values, as for every value the actor schema refuses.

#### Scenario: An actor that opts in
- **WHEN** a person runs `troupe config set actors.tester.onContextFull=compact`
- **THEN** it is recorded, and `tester`'s actor config has `onContextFull` `compact`

#### Scenario: An actor that says nothing
- **WHEN** an actor has no `onContextFull`
- **THEN** its runs are treated as `fail`, unless policy says otherwise

#### Scenario: A value that isn't one of the two
- **WHEN** a person sets `actors.tester.onContextFull` to `summarise`
- **THEN** it is refused, naming the path and the accepted values `fail` and `compact`
- **AND** nothing is recorded
