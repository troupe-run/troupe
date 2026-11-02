# Spec Delta

## ADDED Requirements

### Requirement: An audition records one change, like any other
`troupe init --audition` SHALL record exactly one `Config.Changed` defining the example actor, with lineage like any
config change, checked against the actor schema and its runner's options schema before it is recorded. Plain
`troupe init` SHALL record no config event.

#### Scenario: One change for the actor
- **WHEN** a person runs `troupe init --audition`
- **THEN** the config stream holds one `Config.Changed`, whose entries set `actors.lead`'s runner, options, `expect`
  and, for Claude Code, its character
- **AND** its lineage names who ran it, via `cli`, with a command cause whose id is its change id

#### Scenario: Plain init records nothing
- **WHEN** a person runs `troupe init`
- **THEN** the config stream holds no event

#### Scenario: The audition's config is valid
- **WHEN** the example actor for each runner troupe has is checked against the actor schema and that runner's
  published options schema
- **THEN** it is valid

### Requirement: An audition needs an identity before it makes anything
`troupe init --audition` SHALL work out who is acting before it makes `.troupe/`. When there is no identity, it SHALL
fail as recording any change does, and SHALL make nothing.

#### Scenario: No identity
- **WHEN** no identity source gives an identity and a person runs `troupe init --audition`
- **THEN** it fails with the identity error, and no `.troupe/` is made

### Requirement: The Claude Code audition can edit files on a small budget
The Claude Code example actor SHALL have `runner: claude-code`, options with `maxBudgetUsd` of 1, `permissionMode`
`acceptEdits`, and `allowedTools` holding `Read`, `Write`, `Edit`, `Glob` and `Grep`, an empty `expect`, and a short
character. It SHALL leave `workspace` unset, so its runs work in a worktree.

#### Scenario: The Claude Code actor's file
- **WHEN** a person runs `troupe init --audition`
- **THEN** `.troupe/actors/lead.yaml` holds runner `claude-code`, those options and `expect: []`, and no `workspace`
- **AND** `.troupe/actors/lead.md` holds the character, which is non-empty text

#### Scenario: Any direction can succeed
- **WHEN** the Claude Code example actor is performed with a direction that changes no file, and Claude Code reports
  success
- **THEN** the run ends `succeeded`, because the actor has no effect check

### Requirement: The scripted audition runs offline and checks its effect
The scripted example actor SHALL have `runner: scripted`, an inline script that writes one file and reports success,
and an `expect` naming that file. It SHALL have no character and leave `workspace` unset.

#### Scenario: The scripted actor offline
- **WHEN** a person runs `troupe init --audition --runner scripted`, commits, allows the local stage and runs the
  printed `troupe perform lead`, with no network
- **THEN** the run ends `succeeded`, with its effect check passed on the file the script wrote

#### Scenario: No character for a runner that doesn't read one
- **WHEN** a person runs `troupe init --audition --runner scripted`
- **THEN** no `.troupe/actors/lead.md` is written
