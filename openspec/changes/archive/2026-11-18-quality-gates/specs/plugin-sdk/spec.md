# Spec Delta

## ADDED Requirements

### Requirement: A runner ends its process through the SDK's exit
The plugin SDK SHALL provide `exit_now(code)`, which ends the process at once with `code`, as `os._exit` does, and
every runner in this repository SHALL end its process through it. When coverage.py is already measuring the process,
`exit_now` SHALL first stop it and save what it measured; it SHALL NOT import coverage.py, so outside a coverage run it
is exactly `os._exit` (owner, 2026-11-18).

#### Scenario: Outside a coverage run
- **WHEN** a process that hasn't loaded coverage.py calls `exit_now(3)`
- **THEN** it exits with status 3, runs nothing after the call and no `atexit` hook, and coverage.py is still not loaded

#### Scenario: A runner under coverage
- **WHEN** the scripted runner runs under `coverage run` and ends because its standard input closed
- **THEN** the coverage data holds the runner's lines, the `exit_now` call among them
