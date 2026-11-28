## ADDED Requirements

### Requirement: Each flow is projected to its own file
Each flow in config SHALL be written to `.troupe/flows/<name>.yaml`, holding its `steps` in order, each with the
fields config sets, naming the flow schema as actor files name theirs. A hand edit to it SHALL be swept like an
actor file's, and removing a flow SHALL remove its file.

#### Scenario: A flow's file
- **WHEN** a person sets the flow `review` with steps writer and reviewer, reviewer with a direction
- **THEN** `.troupe/flows/review.yaml` holds both steps in order, reviewer's with its `direction`

#### Scenario: A hand edit to a flow
- **WHEN** a person adds a step to `.troupe/flows/review.yaml` by hand and runs a troupe command
- **THEN** the sweep records the change with an `unknown` actor and the file in its lineage
