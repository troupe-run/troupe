# Spec Delta

## ADDED Requirements

### Requirement: A command run to completion returns as soon as it has ended
Running a short command to completion SHALL return as soon as the command has exited and its output has ended, on
Linux, macOS and Windows, without waiting out any fixed polling interval. While it waits, it SHALL wake only when the
command's output ends, when the output passes its limit, at the announce time and at the timeout.

#### Scenario: A command that exits at once returns at once
- **WHEN** a command that exits at once is run to completion
- **THEN** its result is returned without any wait for a fixed interval after the command has ended, so running it
  costs about what starting it directly costs

#### Scenario: The wait wakes only for the command and its deadlines
- **WHEN** a command runs to completion, whether it ends by itself, passes its timeout or is announced first
- **THEN** every wait is bounded by the next of the announce time and the timeout, and ends early only because the
  command's output ended or passed its limit

#### Scenario: Output past its limit is acted on at once
- **WHEN** a command writes more output than the limit and keeps running
- **THEN** its process tree is killed and the failure naming the limit is raised as soon as the limit is passed,
  without waiting for a polling interval

#### Scenario: A command whose child holds its output open still waits to its timeout
- **WHEN** a command exits while a process it started still holds its output open
- **THEN** it still counts as running, and at the timeout the tree is killed and the timeout failure is raised
