## ADDED Requirements

### Requirement: Status and logs show a run's audit
`troupe status <run>` SHALL show a run's audit beside its outcome: each change outside the declaration, with its
path, what happened to it and the effect it needed; that every change was declared, when none was outside; or that
the audit couldn't run, with its error. `troupe logs <run>` SHALL show the same after the run's outcome. A run with no
audit recorded SHALL show no audit line.

#### Scenario: Status of a timed-out run that changed a file outside its declaration
- **WHEN** a person runs `troupe status <run>` for a run that timed out after writing `notes.md`, which its actor
  doesn't declare
- **THEN** the output shows outcome `timed-out`, and that `notes.md` was added outside the declaration and needed
  `write`

#### Scenario: Logs of a cancelled run that changed a file outside its declaration
- **WHEN** a person runs `troupe logs <run>` for a cancelled run that removed `README.md`, which its actor doesn't
  declare deleting
- **THEN** after the events, the output shows the run's outcome `cancelled`, and that `README.md` was removed outside
  the declaration and needed `delete`

#### Scenario: Status of a failed run that stayed inside its declaration
- **WHEN** a person runs `troupe status <run>` for a failed run whose every change was declared
- **THEN** the output says every change the run made was declared

#### Scenario: Status of a run in the theatre that changed a file outside its declaration
- **WHEN** a person runs `troupe status <run>` for a failed run in the theatre whose audit names `notes.md`
- **THEN** the output also says a run in the theatre counts every change made there while it ran, by anyone

#### Scenario: Status of a run with no audit
- **WHEN** a person runs `troupe status <run>` for a run whose runner never started
- **THEN** the output has no audit line
