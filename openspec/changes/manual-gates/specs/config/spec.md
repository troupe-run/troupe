# Spec Delta

## MODIFIED Requirements

### Requirement: An actor is defined by its runner, options, effect check and character
An actor SHALL have a `runner` (required), `options` (an object, default empty), an optional `effects` (what its runs
may change, spec: effects), `expect` (required: theatre-relative paths the run must create or change, where an empty
list means no file has to change), an optional `character` (text), an optional `workspace`: `worktree` (the
default when it's absent) or `theatre`, optional `runtime` and `model` (spec: runtimes), and optional `approvers`
(spec: gates). Its name SHALL match the client protocol's actor-name pattern.

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

#### Scenario: An actor on a runtime
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted actors.tester.expect=[]
  actors.tester.runtime=ollama actors.tester.model=llama3.2`
- **THEN** `tester`'s runs use the runtime `ollama` with the model `llama3.2`

#### Scenario: An actor whose runs wait for a person
- **WHEN** a person runs `troupe config set 'actors.tester.approvers=["director"]'`
- **THEN** it is recorded, and `tester`'s actor config has approvers `director`

### Requirement: An audition records one change, like any other
`troupe init --audition` SHALL record exactly one `Config.Changed` defining the example actor, with lineage like any
config change, checked against the actor schema, the effects rules and its runner's options schema before it is
recorded. Plain `troupe init` SHALL record no config event.

#### Scenario: One change for the actor
- **WHEN** a person runs `troupe init --audition`
- **THEN** the config stream holds one `Config.Changed`, whose entries set `actors.lead`'s runner, options, effects,
  `expect`, approvers and, for Claude Code, its character
- **AND** its lineage names who ran it, via `cli`, with a command cause whose id is its change id

#### Scenario: Plain init records nothing
- **WHEN** a person runs `troupe init`
- **THEN** the config stream holds no event

#### Scenario: The audition's config is valid
- **WHEN** the example actor for each runner troupe has is checked against the actor schema, the effects rules and
  that runner's published options schema
- **THEN** it is valid

## ADDED Requirements

### Requirement: An actor's approvers are an ordered list of roles
An actor MAY have `approvers`, a list of role names, tried in order at its runs' gate (spec: gates). When it's absent,
its runs SHALL use the built-in default, `[troupe, director]`. Until roles config exists, a name SHALL be `troupe` or
`director`, and any other SHALL be refused, naming the path and the two, and repeating no part of the refused
value (as for every value its shape refuses).

#### Scenario: No approvers set
- **WHEN** an actor has no `approvers`
- **THEN** its runs' approvers are `troupe`, then `director`

#### Scenario: A role that doesn't exist yet
- **WHEN** a person sets `actors.tester.approvers` to `["reviewer"]`
- **THEN** it is refused with `config.invalid`, naming the path, `troupe` and `director`, and not `reviewer`
- **AND** nothing is recorded

### Requirement: An approvers list always ends with a person
An approvers list SHALL end in a role a person can hold, which until roles config is `director`, and `troupe` SHALL
come only first. An empty list, and a list naming a role twice, SHALL be refused. Each refusal SHALL name the path
and say what a valid list is.

#### Scenario: troupe alone
- **WHEN** a person sets `actors.tester.approvers` to `["troupe"]`
- **THEN** it is refused with `config.invalid`, saying the last approver must be a role a person can hold, such as
  `director`

#### Scenario: troupe after a person
- **WHEN** a person sets `actors.tester.approvers` to `["director", "troupe"]`
- **THEN** it is refused, saying `troupe` can come only first

#### Scenario: An empty list
- **WHEN** a person sets `actors.tester.approvers` to `[]`
- **THEN** it is refused, saying a list needs a role a person can hold, and that unsetting it gives the default

#### Scenario: A role twice
- **WHEN** a person sets `actors.tester.approvers` to `["director", "director"]`
- **THEN** it is refused, naming `director`

#### Scenario: A hand edit to the same
- **WHEN** a person writes `approvers: [troupe]` into `.troupe/actors/tester.yaml` and runs any command that uses
  config
- **THEN** the sweep refuses the file, naming it and the rule, and nothing is recorded

### Requirement: An actor that works in place has no approvers
An actor whose `workspace` is `theatre` SHALL NOT have `approvers`, since its work lands as it's made. Setting both
SHALL be refused, naming both paths.

#### Scenario: Approvers on an actor in place
- **WHEN** `actors.tester.workspace` is `theatre` and a person sets `actors.tester.approvers` to `["director"]`
- **THEN** it is refused with `config.invalid`, naming `actors.tester.approvers` and `actors.tester.workspace`
- **AND** nothing is recorded

### Requirement: Every audition's actor waits for a person
Every example actor that `troupe init --audition` defines, for each runner, SHALL set `approvers` to `["director"]`,
so the first run waits at a gate for whoever runs troupe.

#### Scenario: The audition's approvers
- **WHEN** a person runs `troupe init --audition` with any `--runner`
- **THEN** config's `actors.lead` has approvers `director`, and `.troupe/actors/lead.yaml` holds `approvers`
