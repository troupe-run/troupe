## MODIFIED Requirements

### Requirement: Values are checked before a change is recorded
A change SHALL be refused, recording nothing, when the config it would make fails its kind's schema or, for an
actor, when its options fail its runner's published options schema. The error SHALL name the path and the rule. When
an object fits none of a schema's alternatives and exactly one alternative is left once those the object plainly
isn't are set aside, the error SHALL name what's wrong in that alternative, not the alternatives' description.

#### Scenario: A misspelt field
- **WHEN** a person sets `actors.tester.runnr`
- **THEN** it is refused, naming the path and saying the actor has no such field
- **AND** nothing is recorded

#### Scenario: Options the runner doesn't define
- **WHEN** a person sets `actors.tester.options.speed` for the scripted runner
- **THEN** it is refused, naming the path and the scripted runner's options schema

#### Scenario: An object that fits none of the alternatives is checked against the closest
- **WHEN** a person sets a scripted actor's options to `{"script": {"steps": [{"event": {"type": "init", "runner": "x"}}]}}`
- **THEN** it is refused, naming `actors.tester.options.script.steps.0.event.tools` as required and
  `actors.tester.options.script.steps.0.event.runner` as needing a group
- **AND** the error doesn't give a step's description, and doesn't end with two full stops

#### Scenario: Alternatives with no closest one are described
- **WHEN** a person sets an option whose alternatives are a boolean or one of a list to a text outside the list
- **THEN** it is refused with the option's description, ending with one full stop
