## MODIFIED Requirements

### Requirement: Only a whole actor or runtime can be renamed
`config mv` SHALL be refused, recording nothing, with `config.move-not-entity`, when either path isn't
`actors.<name>`, `runtimes.<name>` or `flows.<name>`, or the two paths are of different kinds. The new name SHALL be
checked like any name of its kind, and a flow's new name SHALL NOT be an actor's, or an actor's a flow's.

#### Scenario: A value path
- **WHEN** a person runs `troupe config mv actors.tester.runner actors.tester.model`
- **THEN** it is refused with `config.move-not-entity`, saying only a whole actor, runtime or flow can be renamed

#### Scenario: Across kinds
- **WHEN** a person runs `troupe config mv actors.tester runtimes.tester`
- **THEN** it is refused with `config.move-not-entity`, saying a rename keeps its kind

#### Scenario: An invalid new name
- **WHEN** a person runs `troupe config mv actors.tester actors.Q_A`
- **THEN** it is refused, naming the rule for an actor's name, and nothing is recorded

#### Scenario: Renaming a flow
- **WHEN** a person runs `troupe config mv flows.review flows.check`
- **THEN** one change renames the flow, and `.troupe/flows/check.yaml` replaces `review.yaml`

## ADDED Requirements

### Requirement: An actor's rename carries the flows that name it
When an actor is renamed, the same change SHALL set the actor on every flow step that names the old name.

#### Scenario: A flow naming the actor twice
- **WHEN** the flow `review` is writer, reviewer, writer, and a person runs `troupe config mv actors.writer actors.author`
- **THEN** one change holds the rename and sets steps 1 and 3 of `review` to `author`
