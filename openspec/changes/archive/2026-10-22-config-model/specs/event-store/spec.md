# Spec Delta

## MODIFIED Requirements

### Requirement: A forked stream is detected
A stream with more than one head SHALL be reported as forked. Loading its current state SHALL fail with an error
naming the stream, each head and the file it is in, and the fix, unless the stream's aggregate defines how its forks
merge, in which case it SHALL be read through that merge. The store SHALL NOT pick a winner.

#### Scenario: Two branches append to one stream
- **WHEN** two branches each record version 5 of the same stream with different content, and are merged
- **THEN** loading that stream fails with an error naming both heads and their files
- **AND** the error says to settle the fork

#### Scenario: Appending to a forked stream
- **WHEN** an ordinary event is recorded to a forked stream
- **THEN** it is refused with the same error

#### Scenario: An aggregate that merges its forks
- **WHEN** the config stream is forked by a merge of two branches
- **THEN** reading config works it out from both branches' events, and nothing is refused or recorded

### Requirement: A settling event ends a fork
A settling event SHALL name every head of a forked stream as its parents and carry the settled state. After it,
the stream SHALL have one head, and loading SHALL start from the settling event, never applying events from two
branches. A batch SHALL be able to hold a settling event followed by ordinary events for the same stream.

#### Scenario: Settling a fork
- **WHEN** a settling event naming both heads is recorded on a forked stream
- **THEN** the stream has one head
- **AND** loading it yields the state the settling event carries, plus any later events

#### Scenario: Settling must name every head
- **WHEN** a settling event names only one of two heads
- **THEN** it is refused with an error naming the head it leaves out

#### Scenario: The fork's history stays readable
- **WHEN** a settled stream's history is read
- **THEN** it includes the events from both branches and the settling event

#### Scenario: Settling and a change in one batch
- **WHEN** one batch records a settling event naming both heads, then an ordinary event
- **THEN** both are recorded, all or nothing, and the ordinary event's parent is the settling event

#### Scenario: Two clones settle the same fork the same way
- **WHEN** two clones each record a settling event with the same parents and the same state, and are merged
- **THEN** the two settling events have the same id, and reads return it once
