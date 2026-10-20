## ADDED Requirements

### Requirement: Recording events runs no version-control command while nothing has moved
Stamping an event's lineage with the branch and HEAD SHALL run no version-control command while the branch and HEAD
haven't moved since they were last read. Recording N events with the actor known SHALL run a number of `git`
processes that doesn't grow with N. Each event's lineage SHALL still name the branch and HEAD current when it was
recorded, whichever process moved them.

#### Scenario: Many events cost a fixed number of git processes
- **WHEN** a session records N events in a git theatre where nothing moves, with the actor known, for two different
  values of N
- **THEN** both runs execute the same number of `git` processes

#### Scenario: The plain filesystem adapter runs nothing
- **WHEN** a session records N events in a theatre using the plain filesystem adapter
- **THEN** no command runs, and every event's lineage names that adapter with no branch and no HEAD

#### Scenario: Lineage follows git operations within a session
- **WHEN** one session records an event, then a commit, a switch, a merge or a reset is made, then the session records
  another event
- **THEN** the second event's lineage names the branch and HEAD after that operation

#### Scenario: Lineage follows git operations in a long-lived process
- **WHEN** a separate, long-lived process records events while the test process commits, switches, merges and resets
  between them
- **THEN** each event's lineage names the branch and HEAD current when it was recorded
