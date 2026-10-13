# Spec Delta

## MODIFIED Requirements

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

#### Scenario: Unknown flag after a command
- **WHEN** a user runs `troupe status --bogus`
- **THEN** the exit code is 2
- **AND** the message names `--bogus` and `troupe status`
- **AND** the fix, when there is no near match, points at `troupe status --help`

## ADDED Requirements

### Requirement: A usage problem carries no surface prefix
A usage error's problem SHALL NOT begin with a surface's name or prefix, such as `troupe:`. Each surface SHALL add
its own prefix when it renders the error, so the CLI prints `troupe: ` exactly once at the start of the problem.

#### Scenario: The prefix appears once
- **WHEN** a person runs `troupe perform tester --runner scripted`
- **THEN** the first line of standard error starts with `troupe: ` and does not contain `troupe: troupe:`
- **AND** the error's problem data does not start with `troupe:`

#### Scenario: Every usage shape is prefix-free
- **WHEN** the CLI reports any usage error, whether an unknown command, an unknown flag, a dash-leading value, a
  missing argument, a missing one-of, conflicting options, an extra argument, a missing value, an invalid value or
  the backstop
- **THEN** its problem does not start with `troupe:`

### Requirement: A usage error names the command it concerns and points at its help
A usage error found after the command line has chosen a command SHALL name that command (for example
`troupe perform`) in its problem and in its details, and its fix SHALL point at that command's help
(`troupe perform --help`) unless it gives a more specific fix. A usage error found before any command is chosen SHALL
point at `troupe --help`.

#### Scenario: A command's usage error points at the command's help
- **WHEN** a person runs `troupe logs` with no run
- **THEN** the problem names `troupe logs`
- **AND** the fix says to run `troupe logs --help`

#### Scenario: An error before any command points at the root help
- **WHEN** a person runs `troupe nosuchthing`
- **THEN** the fix points at `troupe --help`

### Requirement: Each usage shape has its own code
Each usage shape SHALL have its own code, exiting 2, with details naming the command and what was wrong:
`usage.missing-argument`, `usage.missing-one-of`, `usage.conflicting-options`, `usage.extra-argument`,
`usage.missing-value` and `usage.invalid-value`. The scenarios define each shape.

#### Scenario: A required option is missing
- **WHEN** a person runs `troupe perform tester --no-effect-check`
- **THEN** it fails with `usage.missing-argument`, naming `troupe perform` and `--runner`

#### Scenario: A required positional is missing
- **WHEN** a person runs `troupe logs`
- **THEN** it fails with `usage.missing-argument`, naming `troupe logs` and the run

#### Scenario: A required one-of group got none
- **WHEN** a person runs `troupe perform tester --runner scripted`
- **THEN** it fails with `usage.missing-one-of`, naming `troupe perform`, `--expect` and `--no-effect-check`

#### Scenario: Two exclusive options given
- **WHEN** a person runs `troupe perform tester --runner scripted --expect out.txt --no-effect-check`
- **THEN** it fails with `usage.conflicting-options`, naming `troupe perform`, `--expect` and `--no-effect-check`

#### Scenario: A repeatable option given twice is not a conflict
- **WHEN** a person gives `--expect a.txt --expect b.txt` and no `--no-effect-check`
- **THEN** no `usage.conflicting-options` error is reported

#### Scenario: Too many positional values
- **WHEN** a person runs `troupe status one two`
- **THEN** it fails with `usage.extra-argument`, naming `troupe status` and `two`

#### Scenario: An option with no value at the end
- **WHEN** a person runs `troupe status --limit`
- **THEN** it fails with `usage.missing-value`, naming `troupe status` and `--limit`

#### Scenario: An option followed by another flag instead of its value
- **WHEN** a person runs `troupe status --limit --json`
- **THEN** it fails with `usage.missing-value`, naming `--limit`

#### Scenario: A value of the wrong type
- **WHEN** a person runs `troupe status --limit notanumber`
- **THEN** it fails with `usage.invalid-value`, naming `troupe status`, `--limit` and `notanumber`

#### Scenario: Values after `--` count as positionals
- **WHEN** a person runs `troupe status -- -5 -6`
- **THEN** it fails with `usage.extra-argument`, naming `-6`

### Requirement: An unanticipated usage problem is still reported as structured data
A usage problem the CLI's own checks do not recognise SHALL be reported as `usage.invalid`, exiting 2, with the
underlying message as its problem (with no surface prefix), the command in its details (or none, before a command is
chosen), and a fix pointing at the relevant help. It SHALL NOT fall through to a success or to another code.

#### Scenario: A parse failure the checks did not anticipate
- **WHEN** the argument parser reports a failure that is not one of the named usage shapes
- **THEN** the error is `usage.invalid`, exits 2, and validates against the protocol's error schema
