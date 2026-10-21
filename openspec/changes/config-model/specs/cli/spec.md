# Spec Delta

## ADDED Requirements

### Requirement: Perform names an actor from config
`troupe perform <actor>` SHALL run the actor as config defines it, taking `--direction <text>` (optional) and
`--rehearse`, and no flag that names a runner, options or an effect check. An actor that isn't in config SHALL be
refused with `config.unknown-actor`, naming the actors config has.

#### Scenario: Perform from config
- **WHEN** config defines `tester` with the scripted runner, a script and `expect: ["out/hello.txt"]`, and a person
  runs `troupe perform tester --direction "write the hello file"`
- **THEN** the run uses that runner, script and effect check, with that direction

#### Scenario: An interim flag
- **WHEN** a person runs `troupe perform tester --runner scripted`
- **THEN** it exits with the usage-error code, naming `--runner` as unknown

#### Scenario: An actor that isn't configured
- **WHEN** a person runs `troupe perform nobody`
- **THEN** it fails with `config.unknown-actor`, naming the actors config has

### Requirement: Every command that changes anything can be rehearsed
Every command that records events or writes files SHALL take `--rehearse` (#137). A rehearsal SHALL run the command's
checks, show what the command would record, write or start, and record nothing, write nothing and start nothing.

#### Scenario: Rehearsing a config change
- **WHEN** a person runs `troupe config set actors.tester.runner=claude-code --rehearse`
- **THEN** it shows the change it would record and the files it would write
- **AND** no event is recorded and no file is written

#### Scenario: Rehearsing a perform
- **WHEN** a person runs `troupe perform tester --rehearse`
- **THEN** it shows the actor, runner, stage and effect check it would run, and the character and direction by hash
  and length
- **AND** no runner is started and no event is recorded

### Requirement: A rehearsal's exit code says what it found
A rehearsal SHALL exit 0 when the command would succeed with nothing to do, with the exit code for "would change"
when it would succeed and change something, and with the refusal's own code when it would be refused.

#### Scenario: Files that are out of date
- **WHEN** a person runs `troupe flush --rehearse` and a config file isn't what config would write
- **THEN** it exits with the "would change" code, naming the file

#### Scenario: Files in line
- **WHEN** every config file is what config would write
- **THEN** `troupe flush --rehearse` exits 0

#### Scenario: A rehearsal that would be refused
- **WHEN** a config file was edited by hand and a person runs `troupe flush --rehearse`
- **THEN** it exits with the code of `config.file-not-troupes`, naming the file

### Requirement: Config and flush commands
The CLI SHALL offer `troupe config set`, `troupe config unset`, `troupe config get` and `troupe flush`, each calling
the core through the client protocol. `troupe config get` SHALL take `--json`, which writes the query's result
exactly in its protocol shape.

#### Scenario: Config get as JSON
- **WHEN** a person runs `troupe config get --json`
- **THEN** standard output is one JSON document that validates against the `config-get` result schema

## REMOVED Requirements

### Requirement: Perform names its runner, options and effect check on the command line
**Reason**: The actor's runner, options and effect check are config (#60). They're no longer given on the command
line, and there are no overrides, so a run is always what config says.
**Migration**: Define the actor with `troupe config set actors.<name>.runner=… actors.<name>.expect=…` (and its
options), then run `troupe perform <name>`. `--instructions` is now `--direction`.

### Requirement: Expected paths are given from the working directory and stay in the theatre
**Reason**: The effect check is the actor's `expect`, which holds theatre-relative paths and is checked when it's
set (spec: config).
**Migration**: Set `actors.<name>.expect` to paths relative to the theatre's root.
