# Spec Delta

## ADDED Requirements

### Requirement: A child's end says whether troupe's kill ended it
After a child process has ended, the platform seam SHALL say whether troupe's kill ended it. This SHALL be true only
when troupe killed the child and the child's exit status is the one that kill produces, on Linux, macOS and Windows.
On Windows, a kill SHALL end the child with an exit code troupe names, distinct from the codes a program commonly
exits with.

#### Scenario: A child troupe killed
- **WHEN** troupe kills a running child and waits for it
- **THEN** the seam says the kill ended it

#### Scenario: A child that exited before a late kill
- **WHEN** a child exits with code 0 and troupe then kills it before it has seen the exit
- **THEN** the child's exit code is 0 and the seam says the kill did not end it

#### Scenario: A child that exits with the kill's status by itself
- **WHEN** a child that troupe never killed ends with the same exit status a kill produces
- **THEN** the seam says the kill did not end it
