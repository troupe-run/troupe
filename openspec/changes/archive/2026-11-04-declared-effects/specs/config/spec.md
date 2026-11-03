# Spec Delta

## MODIFIED Requirements

### Requirement: An actor is defined by its runner, options, effect check and character
An actor SHALL have a `runner` (required), `options` (an object, default empty), an optional `effects` (what its runs
may change, spec: effects), `expect` (required: theatre-relative paths the run must create or change, where an empty
list means no file has to change), an optional `character` (text) and an optional `workspace`: `worktree` (the
default when it's absent) or `theatre`. Its name SHALL match the client protocol's actor-name pattern.

#### Scenario: An actor with no effect check written
- **WHEN** a person sets only `actors.tester.runner`
- **THEN** it is refused, saying `expect` is required and that `[]` means no file has to change

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

#### Scenario: An effect the actor schema doesn't define
- **WHEN** a person sets `actors.tester.effects.network`
- **THEN** it is refused, naming the path and the effects `write`, `delete` and `move`

### Requirement: The Claude Code audition can edit files on a small budget
The Claude Code example actor SHALL have `runner: claude-code`, options with `maxBudgetUsd` of 1 and `allowedTools`
holding `Read`, `Glob` and `Grep`, `effects` with `write: ["**"]`, an empty `expect`, and a short character. It SHALL
leave `permissionMode` and `workspace` unset, so its runs work in a worktree and Claude Code can change only what its
effects declare.

#### Scenario: The Claude Code actor's file
- **WHEN** a person runs `troupe init --audition`
- **THEN** `.troupe/actors/lead.yaml` holds runner `claude-code`, those options, `effects.write: ["**"]` and
  `expect: []`, and no `workspace`
- **AND** `.troupe/actors/lead.md` holds the character, which is non-empty text

#### Scenario: Any direction can succeed
- **WHEN** the Claude Code example actor is performed with a direction that changes no file, or only edits files, and
  Claude Code reports success
- **THEN** the run ends `succeeded`, because no file has to change and every change is declared

### Requirement: The scripted audition runs offline and checks its effect
The scripted example actor SHALL have `runner: scripted`, an inline script that writes one file and reports success,
`effects` with `write` naming that file, and an `expect` naming it too. It SHALL have no character and leave
`workspace` unset.

#### Scenario: The scripted actor offline
- **WHEN** a person runs `troupe init --audition --runner scripted`, commits, allows the local stage and runs the
  printed `troupe perform lead`, with no network
- **THEN** the run ends `succeeded`, with its effect check passed on the file the script wrote and its audit passed

#### Scenario: No character for a runner that doesn't read one
- **WHEN** a person runs `troupe init --audition --runner scripted`
- **THEN** no `.troupe/actors/lead.md` is written

### Requirement: An audition records one change, like any other
`troupe init --audition` SHALL record exactly one `Config.Changed` defining the example actor, with lineage like any
config change, checked against the actor schema, the effects rules and its runner's options schema before it is
recorded. Plain `troupe init` SHALL record no config event.

#### Scenario: One change for the actor
- **WHEN** a person runs `troupe init --audition`
- **THEN** the config stream holds one `Config.Changed`, whose entries set `actors.lead`'s runner, options, effects,
  `expect` and, for Claude Code, its character
- **AND** its lineage names who ran it, via `cli`, with a command cause whose id is its change id

#### Scenario: Plain init records nothing
- **WHEN** a person runs `troupe init`
- **THEN** the config stream holds no event

#### Scenario: The audition's config is valid
- **WHEN** the example actor for each runner troupe has is checked against the actor schema, the effects rules and
  that runner's published options schema
- **THEN** it is valid
