## ADDED Requirements

### Requirement: The audit's findings are part of the outcome
The host SHALL run the audit once the runner has ended, for every run whose runner started, including one that
couldn't finish its handshake, and SHALL return the findings with the outcome: the changes outside the declaration,
which may be none, or the error that kept the audit from running. An outcome whose runner never started SHALL have no
audit. The expected files SHALL be checked only for an `ok` result.

#### Scenario: An error result is audited
- **WHEN** a runner writes a file its actor doesn't declare and sends an `error` result
- **THEN** the outcome is `failed` with `run.error-result`, and its audit names the file

#### Scenario: A runner that started but didn't finish its handshake
- **WHEN** a runner writes a file its actor doesn't declare and then never answers the handshake
- **THEN** the outcome is `could-not-start` with `runner.start-timeout`, and its audit names the file

#### Scenario: A runner that couldn't be started
- **WHEN** a runner's command isn't found
- **THEN** the outcome is `could-not-start` with no audit

#### Scenario: An ok result's audit is its effect check's
- **WHEN** a runner sends an `ok` result and exits 0, and the run changed a file its actor didn't declare
- **THEN** the outcome is `failed` with `effects.outside-declared`, and its audit names the same file
