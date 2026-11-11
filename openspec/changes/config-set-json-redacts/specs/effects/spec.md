## MODIFIED Requirements

### Requirement: A pattern that can't be meant is refused
A pattern SHALL be refused, recording nothing, when it's empty, absolute, contains `..`, `\`, `:`, a control
character, an empty part or `**` inside a part, or starts with `.git` or `.troupe` as its first part. The error SHALL name the actor, the list,
the pattern's position in it and the rule, and SHALL NOT repeat any part of the pattern. The actor schema's pattern and the runner SDK's SHALL accept exactly the same patterns.

#### Scenario: An absolute pattern
- **WHEN** a person sets `actors.tester.effects.write` to `["/tmp/**"]`
- **THEN** it is refused, naming `actors.tester.effects.write`, the pattern's position and that patterns are relative
  to the theatre, and saying runs get scratch space without declaring it, without repeating `/tmp/**`

#### Scenario: A pattern into troupe's own directory
- **WHEN** a person sets `actors.tester.effects.write` to `[".troupe/**"]`
- **THEN** it is refused, saying `.troupe/` is troupe's own and no effect can allow changing it

#### Scenario: The schema and the SDK agree
- **WHEN** generated patterns and near misses are checked by the actor schema's pattern and by the SDK's
- **THEN** both accept or both refuse each one

#### Scenario: A pattern holding a password
- **WHEN** a person runs `troupe config set --json 'actors.tester.effects.write=["https://user:<canary>@example.com/v1"]'`
- **THEN** it is refused with `config.invalid`, naming `actors.tester.effects.write`, and neither the standard error
  nor the client message holds the canary or `example.com`
