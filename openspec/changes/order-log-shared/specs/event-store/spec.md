## MODIFIED Requirements

### Requirement: Notification IDs are local, dense and never renumbered
Notification IDs SHALL be assigned locally, per branch, from 1 with no gaps. Once issued on a branch, an ID SHALL
always name the same event there. Nothing that orders events SHALL be stored in a tracked file. This SHALL hold
however many stores, in one process or several, read and write one theatre at once.

#### Scenario: IDs survive a restart
- **WHEN** events are recorded, the store is closed and opened again
- **THEN** every notification ID names the same event as before

#### Scenario: A merge appends, it never renumbers
- **WHEN** a merge brings in events, including events recorded earlier than ones already numbered
- **THEN** every previously issued notification ID still names the same event
- **AND** the incoming events get the next IDs, in a deterministic order

#### Scenario: The ordering is not in git
- **WHEN** events are recorded
- **THEN** no tracked file holds notification IDs

#### Scenario: Two stores on one theatre
- **WHEN** two stores on one theatre take turns recording events and reading notifications, in one process or in
  two
- **THEN** each event gets exactly one notification ID, and both stores give every ID the same event
- **AND** a store opened afterwards loads the order without error

### Requirement: Followers' positions are local
A follower's position (the last notification it processed) SHALL be stored as a plain integer, outside git,
per branch. A position recorded by one store SHALL be seen by every other store on the theatre before it records
another.

#### Scenario: Positions are kept per branch
- **WHEN** a follower records its position on one branch, and the branch is switched
- **THEN** the follower's position on the other branch is its own

#### Scenario: A position recorded by another store
- **WHEN** one store records a follower's position, and a second store on the same theatre then records a position
  for that follower that isn't greater
- **THEN** the second store refuses it as a conflict
