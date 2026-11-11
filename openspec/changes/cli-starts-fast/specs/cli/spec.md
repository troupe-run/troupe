# Spec Delta

## ADDED Requirements

### Requirement: Starting troupe loads only what parsing needs
Loading the command line SHALL load only what reading a command line needs: the command table, the parser and error
rendering. The modules that commands use to do their work (schema checking, YAML, the async runtime, package
metadata, the core's command handlers) SHALL load only when a command that uses them runs. Asking for the version,
for help, or making a usage error SHALL load none of them, apart from package metadata for the version.

#### Scenario: Importing the command line
- **WHEN** a fresh interpreter imports troupe's command line and nothing else
- **THEN** none of the named heavy modules is loaded: package metadata, schema checking and its schema registry,
  YAML, the async runtime, the core's command handlers, and the runner effects module

#### Scenario: Asking for help
- **WHEN** a user runs `troupe --help`, or `troupe` with no command
- **THEN** the help is printed as before
- **AND** none of the named heavy modules has been loaded

#### Scenario: A usage error
- **WHEN** a user runs `troupe` with an unknown command or a refused argument
- **THEN** the usage error is reported as before, with the same code and exit code
- **AND** none of the named heavy modules has been loaded

#### Scenario: Asking for the version
- **WHEN** a user runs `troupe --version`
- **THEN** the version line is printed as before
- **AND** of the named heavy modules, only package metadata has been loaded

#### Scenario: The check counts modules, not time
- **WHEN** the check for these scenarios runs on a slow or loaded machine
- **THEN** its outcome depends only on which modules a fresh interpreter loaded, never on how long it took

### Requirement: A command loads only its own handlers
Running a command SHALL load the core's handlers for that command's method and not the handlers of commands in
other families (runs, config, init). A call naming a method troupe doesn't offer SHALL still be refused with
`client.unknown-method`, listing every method troupe offers.

#### Scenario: A run query
- **WHEN** a user runs `troupe status` in a theatre
- **THEN** the status is shown as before
- **AND** the core's config and init handlers have not been loaded

#### Scenario: A config command
- **WHEN** a user runs `troupe config get` in a theatre
- **THEN** the value is shown as before
- **AND** the core's run and init handlers have not been loaded

#### Scenario: An unknown method still lists every method
- **WHEN** a surface calls a method troupe doesn't offer
- **THEN** it is refused with `client.unknown-method`
- **AND** the error lists every method troupe offers, the same list as before
