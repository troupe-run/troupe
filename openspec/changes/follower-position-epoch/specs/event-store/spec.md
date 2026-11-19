## MODIFIED Requirements

### Requirement: Notification IDs are local, dense and never renumbered
Notification IDs SHALL be assigned locally, per branch, from 1 with no gaps until the order is rebuilt; a rebuilt
order SHALL be numbered with no gaps from after the highest ID ever issued on the branch, so an ID is never reused
there. Once issued on a branch, an ID SHALL always name the same event there. Nothing that orders events SHALL
be stored in a tracked file. This SHALL hold however many stores, in one process or several, read and write one
theatre at once.

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

#### Scenario: A rebuilt order never reuses an ID
- **WHEN** events have been given IDs 1 to 3, and the order is rebuilt with the same three events
- **THEN** the rebuilt order gives them IDs after 3, with no gaps between them
- **AND** no ID from 1 to 3 names an event any more

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

#### Scenario: A position read before the rebuild and recorded after it
- **WHEN** a follower reads IDs 1 and 2, the order is then rebuilt by another store, and the follower records its
  position as 2
- **THEN** the follower's next read, from just after its position, gives it every event of the rebuilt order

#### Scenario: A live subscription across a rebuild
- **WHEN** a subscriber has been given IDs 1 to 3, the order is rebuilt, and an event is recorded
- **THEN** the subscription gives it every event of the rebuilt order, then the new event

## ADDED Requirements

### Requirement: The highest ID issued outlives the order file
The store SHALL keep, per branch and outside git, a record of the highest notification ID it may have issued, apart
from the order file. When the order file is missing, damaged or rebuilt, the new order SHALL be numbered after that
record, so deleting the order file by hand never makes an ID name a different event.

#### Scenario: The order file is deleted by hand
- **WHEN** events have been given IDs 1 to 3, and the order file is deleted
- **THEN** the store numbers the events again from an ID after 3

#### Scenario: The record is damaged
- **WHEN** the record of the highest ID issued isn't valid
- **THEN** reads fail with an error naming the file and the fix
