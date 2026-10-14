# Spec Delta

## ADDED Requirements

### Requirement: A run's ending records how the runner ended
A run's `ending` SHALL be `killed` exactly when the host killed the runner and that kill is what ended it. A runner
that exits by itself SHALL be `exited`, with its own exit code, even when the host had decided to kill it or had
already sent the kill. The host SHALL decide this from how the process ended, not from whether it had seen the
process end before killing it.

#### Scenario: Killed for a violation while still running
- **WHEN** a runner breaks the contract and keeps running, and nothing has asked it to exit
- **THEN** the host kills it and the run's ending is `killed`

#### Scenario: The runner exits before the kill lands
- **WHEN** a runner sends its `result`, the host sends `shutdown`, the runner sends a late event and then answers
  `shutdown` by exiting 0 before the host's kill takes effect
- **THEN** the outcome is `crashed` with the protocol error naming the late event, and the ending is `exited` with
  exit code 0

#### Scenario: An ok result whose runner exits as the grace period ends
- **WHEN** a runner sends an `ok` result, the effect check passes, and the runner exits 0 by itself just as the
  grace period after `shutdown` passes, before the host's kill takes effect
- **THEN** the ending is `exited` with exit code 0 and the outcome is `succeeded`

#### Scenario: Ignoring cancel still ends killed
- **WHEN** a run is cancelled and the runner keeps running past the grace period
- **THEN** the runner is killed and the run's ending is `killed`
