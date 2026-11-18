# Spec Delta

## MODIFIED Requirements

### Requirement: Runners start with an explicit environment
The host SHALL start a runner under the runner environment policy, a named default that selects one variable from the
host, coverage.py's `COVERAGE_PROCESS_CONFIG`, and nothing else (owner, 2026-11-18). The runner gets that variable when
the host has it, the variables the caller names, and the minimum the operating system needs to start a process. It
SHALL NOT pass through anything else of the host's environment.

#### Scenario: Host secret is not inherited
- **WHEN** the host process has an environment variable the caller did not name
- **THEN** the runner does not see that variable

#### Scenario: Named variable is passed
- **WHEN** the caller names an environment variable and its value
- **THEN** the runner sees it

#### Scenario: Coverage's variable is the only one passed
- **WHEN** the host process has `COVERAGE_PROCESS_CONFIG` and other variables, among them credentials and variables
  whose names start with `COVERAGE_`
- **THEN** the runner sees `COVERAGE_PROCESS_CONFIG` with the host's value, and none of the others
