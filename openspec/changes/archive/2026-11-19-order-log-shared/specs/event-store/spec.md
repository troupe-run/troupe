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

### Requirement: The local order rebuilds itself when events disappear
When an event named by the local order is no longer present (an event file removed by hand, or a reset), or the
order is inconsistent (one ID names two events, an event has two IDs, or an ID is out of sequence), the store SHALL
rebuild the branch's order from the events present, and report it. Followers' positions recorded against the old
order SHALL be discarded, so their projections are rebuilt and nothing is skipped.

#### Scenario: An event file is removed
- **WHEN** an uncommitted event file is deleted, and the store is opened
- **THEN** the order is rebuilt without its events
- **AND** a notice says the order was rebuilt and why
- **AND** every follower starts again from the beginning

#### Scenario: One ID names two events
- **WHEN** the local order gives one notification ID to two different events, and the store is opened
- **THEN** the order is rebuilt, and each event has exactly one ID
- **AND** a notice says the order was rebuilt, naming the line and the reason
- **AND** every follower starts again from the beginning

## ADDED Requirements

### Requirement: Repeated lines in the local order are dropped
A line of the local order that repeats an ID already given to the same event SHALL be ignored when the order is
read. The store SHALL rewrite the file without it, keeping the order's epoch, and report how many lines it dropped.
Followers' positions SHALL still count.

#### Scenario: An order with repeated lines
- **WHEN** the local order repeats a line (the same ID for the same event), and the store is opened
- **THEN** every ID names the event it named before, and the file no longer repeats the line
- **AND** a notice says the order was repaired
- **AND** followers keep their positions
