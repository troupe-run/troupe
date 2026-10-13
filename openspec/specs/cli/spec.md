# cli Specification

## Purpose

The command-line surface of troupe: a thin client over the core's commands and queries, covering how it is
invoked, how global flags are parsed, and how results and errors are rendered and reported through exit codes.

## Requirements

### Requirement: Version reporting
`troupe --version` SHALL print the installed troupe version to standard output and exit 0, without needing a
theatre, an identity or a running daemon.

#### Scenario: Version outside any theatre
- **WHEN** a user runs `troupe --version` in a directory with no `.troupe/`
- **THEN** standard output contains the installed version string
- **AND** the exit code is 0

### Requirement: Global flags are accepted anywhere
A global flag SHALL have the same effect whether it appears before or after the subcommand name.

#### Scenario: Flag before the subcommand
- **WHEN** a user runs `troupe --version`
- **THEN** the version is printed

#### Scenario: Same flag after a subcommand
- **WHEN** a user runs a subcommand with a global flag placed after the subcommand name
- **THEN** the result is the same as with the flag placed before the subcommand name

### Requirement: Dash-leading values follow the `--` convention
A positional value that begins with `-` SHALL be accepted only after a `--` separator. Without it, the CLI SHALL
treat the value as an option and report a usage error that names the `--` fix.

#### Scenario: Dash-leading value without separator
- **WHEN** a user passes a positional value `-5` without a preceding `--`
- **THEN** the CLI exits with the usage-error code
- **AND** the message names the value and says to put `--` before it

### Requirement: Errors are rendered from structured data
Every error SHALL originate as structured data with a problem, an optional path, and a fix. The CLI SHALL render it
to standard error, write nothing to standard output, and exit non-zero. The structured shape SHALL be defined once,
in the language-neutral protocol, so other surfaces can render the same error their own way.

#### Scenario: An error names the problem and the fix
- **WHEN** a command fails
- **THEN** standard error contains the problem and the fix
- **AND** it contains the path when the error concerns a file or directory
- **AND** standard output is empty
- **AND** the exit code is non-zero

#### Scenario: Error data matches the protocol schema
- **WHEN** any error the CLI can produce is serialised as data
- **THEN** it validates against the protocol's error schema, including the details schema for its code

### Requirement: Usage errors and unknown commands
A usage error SHALL exit with code 2. An unknown subcommand or flag SHALL be reported as a usage error that names
what was not recognised and, where one exists, the closest valid alternative.

#### Scenario: Unknown subcommand with a near match
- **WHEN** a user runs `troupe verison`
- **THEN** the exit code is 2
- **AND** the message names `verison` as unknown and suggests `--version`

#### Scenario: Unknown flag
- **WHEN** a user passes a flag the CLI does not define
- **THEN** the exit code is 2
- **AND** the message names the flag

### Requirement: Exit codes are defined in one place
Every exit code the CLI can return SHALL be defined in a single named table that the CLI and its documentation both
use. The CLI SHALL NOT return a code that is absent from that table.

#### Scenario: Every returned code is documented
- **WHEN** the CLI exits for any reason covered by the test suite
- **THEN** the exit code appears in the exit-code table

### Requirement: The theatre is found from the working directory
A command that needs a theatre SHALL use the nearest directory, from the working directory upwards, that contains
`.troupe/`. If there is none, it SHALL fail with `theatre.not-found`, naming the directory it searched from, and SHALL
NOT create one.

#### Scenario: Run from a subdirectory
- **WHEN** a person runs `troupe status` in `src/` of a project whose root holds `.troupe/`
- **THEN** the project's root is the theatre

#### Scenario: No theatre
- **WHEN** a person runs `troupe perform tester ...` in a directory with no `.troupe/` above it
- **THEN** it fails with `theatre.not-found`, naming that directory
- **AND** no `.troupe/` is created

### Requirement: Perform names its runner, options and effect check on the command line
Until actors are configured, `troupe perform <actor>` SHALL take `--runner <name>` (required), `--runner-options
<file>` (a JSON object, optional), `--instructions <text>` (optional), and exactly one of `--expect <path>`
(repeatable) or `--no-effect-check`.

#### Scenario: No effect check given
- **WHEN** a person runs `troupe perform tester --runner scripted` with neither `--expect` nor `--no-effect-check`
- **THEN** it exits with the usage-error code, saying to give one of them

#### Scenario: Both effect check flags
- **WHEN** a person gives both `--expect out.txt` and `--no-effect-check`
- **THEN** it exits with the usage-error code

#### Scenario: An unknown runner
- **WHEN** a person runs `troupe perform tester --runner claude --no-effect-check`
- **THEN** it fails with `runner.unknown`, naming the runners it knows

#### Scenario: Runner options that aren't a JSON object
- **WHEN** the file given to `--runner-options` holds a JSON array, a duplicated key, `NaN`, or isn't JSON
- **THEN** it fails with `perform.options-invalid`, naming the file and what was wrong

### Requirement: Expected paths are given from the working directory and stay in the theatre
`--expect` paths SHALL be read relative to the working directory. A path outside the theatre SHALL be refused with
`perform.path-outside-theatre`, naming it.

#### Scenario: A path from a subdirectory
- **WHEN** a person in `src/` runs `troupe perform tester --runner scripted --expect out.txt`
- **THEN** the effect check expects `src/out.txt` in the theatre

#### Scenario: A path outside the theatre
- **WHEN** a person gives `--expect ../elsewhere.txt` from the theatre's root
- **THEN** it fails with `perform.path-outside-theatre`, naming the path

### Requirement: Perform shows progress on standard error and the result on standard output
`troupe perform` SHALL write the run id at once, then each run event and notice as it happens, to standard error. On
success it SHALL write the run id and `succeeded` to standard output. Otherwise standard output SHALL stay empty, and
the run's error SHALL be shown on standard error with the run id.

#### Scenario: Progress while a run is going
- **WHEN** a run is going
- **THEN** standard error shows the run id before the first event, and a line for each event as it is recorded

#### Scenario: A failed run
- **WHEN** a run ends `failed`
- **THEN** standard output is empty
- **AND** standard error shows the run id, the problem and the fix

### Requirement: Perform's exit code follows the run's outcome
`troupe perform` SHALL exit 0 when the run `succeeded`, 130 when it was `cancelled`, and 1 for every other outcome. A
`perform` refused before the run starts SHALL exit with its error's code.

#### Scenario: Cancelled with Ctrl-C
- **WHEN** a person cancels a run with Ctrl-C
- **THEN** `troupe perform` exits 130, on Linux, macOS and Windows

#### Scenario: A crashed run
- **WHEN** a run ends `crashed`
- **THEN** `troupe perform` exits 1

### Requirement: Status and logs commands
`troupe status [<run>] [--limit <n>]` SHALL show runs, and `troupe logs <run> [--follow]` SHALL show a run's events,
each as the `status` and `logs` queries return them. Both SHALL show the store's notices on standard error.

#### Scenario: Logs from another terminal
- **WHEN** a person runs `troupe logs <run> --follow` in another terminal while the run is going
- **THEN** each event appears as it is recorded, and the command exits 0 when the run's end is recorded

### Requirement: Query results as JSON
`troupe status` and `troupe logs` SHALL take `--json`, which writes the query's result to standard output exactly in
its protocol shape. With `--follow`, each update SHALL be written as one line, then the result.

#### Scenario: Status as JSON
- **WHEN** a person runs `troupe status --json`
- **THEN** standard output is one JSON document that validates against the `status` result schema
