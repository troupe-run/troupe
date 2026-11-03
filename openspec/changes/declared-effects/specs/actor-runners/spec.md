# Spec Delta

## MODIFIED Requirements

### Requirement: Success needs an ok result, a passing effect check and a clean exit
The outcome SHALL be `succeeded` only when the run's `result` event has status `ok`, the run's effect check passes,
and the runner exits with code 0 after `shutdown`. The effect check SHALL pass only when every expected file was
made or changed and the audit of the run's changes against its declared effects passes (spec: effects). With no
expected files, the effect check SHALL still audit the run's changes.

#### Scenario: Result ok but declared output missing
- **WHEN** a runner reports status `ok` but a file the run was expected to produce does not exist
- **THEN** the outcome is `failed` with an error naming the missing path

#### Scenario: Result ok and declared output written
- **WHEN** a runner reports status `ok`, every expected file exists with changed contents, every change is declared,
  and the runner exits 0
- **THEN** the outcome is `succeeded`

#### Scenario: Result ok and a change outside the declaration
- **WHEN** a runner reports status `ok` and exits 0, but the run changed a file its actor didn't declare
- **THEN** the outcome is `failed` with an error naming the file and the effect it needed

#### Scenario: Success result with a non-zero exit code
- **WHEN** a runner reports status `ok`, the effect check passes, and the runner then exits with code 3
- **THEN** the outcome is `failed` with an error saying the runner reported success but exited with code 3, so the
  run's state is uncertain

#### Scenario: Success result, then killed during shutdown
- **WHEN** a runner reports status `ok`, the effect check passes, and the runner does not exit within the grace
  period after `shutdown` and is killed
- **THEN** the outcome is `failed` with the same uncertain-state error

### Requirement: Any conforming runner can be checked
troupe SHALL provide a conformance suite that runs against any runner command and checks the runner against this
contract: the handshake, `init` first and saying how the runner applies the effects, a run start carrying effects and
a scratch directory, sequence numbers, the result, cancel, shutdown, and exit on end of input.

#### Scenario: Scripted runner conforms
- **WHEN** the conformance suite runs against the scripted runner
- **THEN** every check passes

#### Scenario: A runner that doesn't say how it applies the effects
- **WHEN** the suite runs against a runner whose `init` has no `effects`
- **THEN** the suite fails, naming the `init` event and `effects`
