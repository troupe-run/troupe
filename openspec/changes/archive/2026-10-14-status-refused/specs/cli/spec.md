# Spec Delta

## MODIFIED Requirements

### Requirement: Dash-leading values follow the `--` convention
A positional value that begins with `-` SHALL be accepted only after a `--` separator. Without it, the CLI SHALL
treat the value as an option and report a usage error that names the `--` fix. A separator with nothing after it
SHALL change nothing: the line SHALL give the same result as the same line without it.

#### Scenario: Dash-leading value without separator
- **WHEN** a user passes a positional value `-5` without a preceding `--`
- **THEN** the CLI exits with the usage-error code
- **AND** the message names the value and says to put `--` before it

#### Scenario: A separator with nothing after it, once the positionals are filled
- **WHEN** a user runs `troupe status x --json --`
- **THEN** it parses exactly as `troupe status x --json` does, with run `x` and JSON output
- **AND** it is not refused as `usage.invalid`

#### Scenario: A trailing separator never changes the outcome
- **WHEN** a command line that contains no `--` gets one `--` added at its end, after the command
- **THEN** the result is the same as without it: the same parsed arguments, or the same usage error code

#### Scenario: A `--` after the separator is a value
- **WHEN** a user runs `troupe status x -- --`
- **THEN** the second `--` is a positional value, and it fails with `usage.extra-argument`, naming `--`
