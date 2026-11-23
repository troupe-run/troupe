## MODIFIED Requirements

### Requirement: Events are never classified or dropped
The store SHALL keep every event that was recorded on the current branch, unless a person drops it through the
store's drop. It SHALL NOT classify events as abandoned or stashed, and SHALL never drop an event of its own accord.
An edit and the edit that reverts it SHALL both stay recorded until a person drops them.

#### Scenario: An edit and its revert
- **WHEN** a stream is changed from 3 to 5, and then a later event changes it back to 3
- **THEN** its history reads 3, 5, 3

#### Scenario: Stash and pop
- **WHEN** events recorded around a `git stash` and `git stash pop` are read
- **THEN** every recorded event is present, in the order recorded

## ADDED Requirements

### Requirement: A drop removes only whole uncommitted segments of this branch
The store's drop SHALL remove the segments holding the events it is given, latest first, only when every recording
of each is in an uncommitted segment of the current branch holding none but those events, and no other event names
one as a parent. Otherwise it SHALL refuse with `events.not-droppable`, naming the reason and segments.

#### Scenario: Dropping events alone in their segments
- **WHEN** two events are recorded by two sessions on the current branch, uncommitted, and nothing names them, and
  the store is asked to drop both
- **THEN** both segments are removed, reads no longer return the events, and the order is rebuilt with a notice

#### Scenario: A segment that holds another event
- **WHEN** the store is asked to drop one of two events in the same segment
- **THEN** it is refused with `events.not-droppable`, naming the segment, and nothing is removed

#### Scenario: A committed segment
- **WHEN** the store is asked to drop an event whose segment is committed
- **THEN** it is refused with `events.not-droppable`, saying the segment is committed, and nothing is removed

#### Scenario: An event another event names as its parent
- **WHEN** the store is asked to drop an event that a later event, not being dropped, names as its parent
- **THEN** it is refused with `events.not-droppable`, naming the later event, and nothing is removed

#### Scenario: A removal that fails partway
- **WHEN** removing the segment of the later of two events succeeds and removing the earlier one's fails
- **THEN** it is refused with `events.not-droppable` naming the segment left, and the earlier event still reads

#### Scenario: A check the caller gives refuses
- **WHEN** the caller's check, run while the store holds its write lock, raises an error
- **THEN** the drop is refused with that error, and nothing is removed

### Requirement: A batch can require events that must still be here
Recording a batch SHALL accept events it needs still to be present, checked while holding the write lock. When any
is gone, the batch SHALL be refused with `events.required-missing`, naming each missing event, and nothing written.

#### Scenario: A required event was dropped
- **WHEN** a session reads an event, another drops it, and the first records a batch requiring it
- **THEN** it is refused with `events.required-missing`, naming the event, and no segment is written

#### Scenario: Required events still here
- **WHEN** a batch requires events that are present
- **THEN** it is recorded as any batch is
