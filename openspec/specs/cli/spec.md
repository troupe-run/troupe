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
- **THEN** it validates against the protocol's error schema

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
