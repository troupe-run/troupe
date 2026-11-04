# Spec Delta

## ADDED Requirements

### Requirement: Config's kinds are actors and runtimes
Config SHALL have two kinds, `actors` and `runtimes` (spec: runtimes). Any other top-level key SHALL be refused,
naming the key and both kinds. A change SHALL be checked against every rule that spans the kinds, such as an actor
naming a runtime that exists.

#### Scenario: A kind that doesn't exist
- **WHEN** a person sets `services.openai.endpoint`
- **THEN** it is refused, naming `services` and the kinds `actors` and `runtimes`

#### Scenario: Removing a runtime an actor uses
- **WHEN** config defines `runtimes.myhost`, `actors.tester.runtime` is `myhost`, and a person unsets
  `runtimes.myhost`
- **THEN** it is refused, naming `actors.tester.runtime`, and nothing is recorded

#### Scenario: A merge that removes a runtime an actor uses
- **WHEN** one branch unsets `runtimes.myhost` and another sets `actors.tester.runtime=myhost`, and they are merged
- **THEN** the merged config is a conflict, naming `actors.tester.runtime`

## MODIFIED Requirements

### Requirement: An actor is defined by its runner, options, effect check and character
An actor SHALL have a `runner` (required), `options` (an object, default empty), an optional `effects` (what its runs
may change, spec: effects), `expect` (required: theatre-relative paths the run must create or change, where an empty
list means no file has to change), an optional `character` (text), an optional `workspace`: `worktree` (the
default when it's absent) or `theatre`, and optional `runtime` and `model` (spec: runtimes). Its name SHALL match
the client protocol's actor-name pattern.

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

### Requirement: Config commands
`troupe config set <path>=<value>…` SHALL set values, with `<path>=@<file>` reading a value from a file;
`troupe config unset <path>…` SHALL remove values or groups; and `troupe config get [<path>]` SHALL show the merged
config, or the value or group at a path, and with `--resolved`, a runtime's resolved values (spec: runtimes). A change
SHALL accept `--reason`, recorded in its lineage.

#### Scenario: A character from a file
- **WHEN** a person runs `troupe config set actors.tester.character=@tester-character.md`
- **THEN** the character is that file's text exactly

#### Scenario: A reason
- **WHEN** a person runs `troupe config set actors.tester.runner=scripted --reason "offline tests"`
- **THEN** the change's lineage records the reason

#### Scenario: Resolved runtimes
- **WHEN** a person runs `troupe config get --resolved`
- **THEN** it shows every runtime, built-in or in config, with each value's source
