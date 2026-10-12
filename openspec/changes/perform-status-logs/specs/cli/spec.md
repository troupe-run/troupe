# Spec Delta

## ADDED Requirements

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
