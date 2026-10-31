## MODIFIED Requirements

### Requirement: Killing a child kills its whole process tree
A child process SHALL start in its own process group (or the platform's equivalent), so that killing it also kills
every process it started, including grandchildren, on Linux, macOS and Windows. This SHALL hold for a grandchild the
child starts the moment it begins running, before troupe could act, whether the child was started to be talked to
or run to completion.

#### Scenario: Grandchild is killed
- **WHEN** a child that has started a grandchild process is killed
- **THEN** both the child and the grandchild are no longer running

#### Scenario: A grandchild started straight away is killed
- **WHEN** a child starts a grandchild as the first thing it does, the grandchild holds the child's output open, and
  the child is then killed
- **THEN** the child and the grandchild are both no longer running, and waiting for the child ends

#### Scenario: A command run to completion that starts a grandchild straight away
- **WHEN** a command run to completion starts a grandchild as the first thing it does and is still running when its
  timeout passes
- **THEN** the command and the grandchild are both killed, and the failure names the command and the timeout

## ADDED Requirements

### Requirement: Waiting for a child ends once it has exited, whatever output was left unread
Once a child has exited, waiting for it SHALL end on Linux, macOS and Windows, even when a caller stopped reading its
output part-way, such as at a line longer than the maximum. The output the child wrote SHALL still be readable after
the wait, and none of it SHALL be dropped.

#### Scenario: A killed child whose over-long line was refused
- **WHEN** a child writes a line longer than the maximum and keeps running, reading that line reports the error
  naming the maximum, and the child is then killed
- **THEN** waiting for it ends, with the kill's exit status

#### Scenario: A child that exits by itself after an over-long line
- **WHEN** a child writes a line longer than the maximum and exits, and reading reports the error before the line
  has all arrived or after
- **THEN** waiting for it ends either way
