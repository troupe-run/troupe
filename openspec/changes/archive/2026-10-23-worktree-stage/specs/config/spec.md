# Spec Delta

## MODIFIED Requirements

### Requirement: An actor is defined by its runner, options, effect check and character
An actor SHALL have a `runner` (required), `options` (an object, default empty), `expect` (required: theatre-relative
paths the run must create or change, where an empty list means no effect check), an optional `character` (text) and
an optional `workspace`: `worktree` (the default when it's absent) or `theatre`. Its name SHALL match the client
protocol's actor-name pattern.

#### Scenario: An actor with no effect check written
- **WHEN** a person sets only `actors.tester.runner`
- **THEN** it is refused, saying `expect` is required and that `[]` means no effect check

#### Scenario: An effect check path outside the theatre
- **WHEN** a person sets `actors.tester.expect` to `["../elsewhere.txt"]`
- **THEN** it is refused, naming the path

#### Scenario: An actor name that doesn't fit
- **WHEN** a person sets `actors.Tester.runner`
- **THEN** it is refused, naming the name and the pattern

#### Scenario: Running in place
- **WHEN** a person runs `troupe config set actors.tester.workspace=theatre`
- **THEN** `tester`'s runs work in the theatre

#### Scenario: A workspace that doesn't exist
- **WHEN** a person sets `actors.tester.workspace` to `sandbox`
- **THEN** it is refused, naming the path, `sandbox`, and the accepted values `worktree` and `theatre`
