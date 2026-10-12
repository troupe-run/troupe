# Spec Delta

## Purpose

Records troupe's events as append-only text that git can merge without conflicts, and reads them back in a stable
local order that meets the `eventsourcing` library's recorder contract, across branches, merges and forks.

## ADDED Requirements

### Requirement: Events are stored as mergeable text
Events SHALL be stored as UTF-8 JSON Lines, one event per line, in files under the theatre's tracked event
directory. A record SHALL be strict JSON, both written and read: no duplicate keys, no `NaN` or `Infinity`. Its
payload SHALL be readable JSON wherever it is JSON, not an opaque blob.

#### Scenario: A recorded event is one readable line
- **WHEN** an event whose payload is a JSON object is recorded
- **THEN** the event directory holds exactly one new line for it
- **AND** that line parses as JSON and validates against the protocol's event-record schema
- **AND** the payload's fields appear in the line as JSON, not encoded

#### Scenario: A duplicate key is refused on read
- **WHEN** a segment line holds an object with the same key twice
- **THEN** reads fail with an error naming the file and the line

#### Scenario: A non-finite number is refused on read
- **WHEN** a segment line holds `NaN`, `Infinity` or `-Infinity`
- **THEN** reads fail with an error naming the file and the line

#### Scenario: A non-JSON payload round-trips exactly
- **WHEN** an event whose payload bytes are not canonical JSON (for example, encrypted or compressed) is recorded
  and read back
- **THEN** the bytes read back equal the bytes recorded

### Requirement: Each session writes its own segment
Every session that records events SHALL append to its own segment file. A segment SHALL only ever be appended to,
SHALL hold events for one branch, and SHALL NOT be written by any other session. A session SHALL create its
segment only when it first records an event.

#### Scenario: Two branches never touch the same file
- **WHEN** events are recorded on two branches from the same starting commit, and the branches are merged with git
- **THEN** the merge has no conflicts in the event directory

#### Scenario: Branch changes mid-session
- **WHEN** a session records an event, the branch changes, and the session records another event
- **THEN** the second event is in a different segment from the first

#### Scenario: Reads create no files
- **WHEN** events are only read
- **THEN** no file is created or changed in the event directory

### Requirement: Event IDs are content hashes that ignore lineage
Each event SHALL be identified by a hash of what it changed: its stream, version, type, parents and payload. The
hash SHALL leave out the event's wall time and all of its lineage.

#### Scenario: Two clones make the same change
- **WHEN** two clones each record an event with the same stream, version, type, parents and payload, with
  different actors, times and branches
- **THEN** both events have the same ID

#### Scenario: Different content gives a different ID
- **WHEN** two events differ only in their payload
- **THEN** their IDs differ

#### Scenario: The same event arriving twice is one event
- **WHEN** a merge brings in an event whose ID is already present
- **THEN** reads return that event once
- **AND** both recordings' lineage remain readable

### Requirement: The store meets the library's recorder contract
The store SHALL pass the `eventsourcing` library's own recorder test suite, unmodified, for the aggregate,
application, non-interleaving, tracking, process and infrastructure-factory cases, and the opt-in subscription
case.

#### Scenario: The library's suite passes
- **WHEN** the library's recorder test cases run against the store
- **THEN** every test passes, and none is skipped or replaced

### Requirement: Versions are unique within a stream
Recording an event whose stream and version are already recorded on the current branch SHALL raise the library's
integrity error. A batch with any conflict SHALL record none of its events.

#### Scenario: Duplicate version
- **WHEN** an event is recorded at a stream and version that is already recorded
- **THEN** the library's integrity error is raised
- **AND** nothing is written

#### Scenario: Conflict inside a batch
- **WHEN** a batch is recorded and only its last event conflicts
- **THEN** no event from the batch is recorded

#### Scenario: Two processes race for the same version
- **WHEN** two processes record the same stream and version at the same time
- **THEN** exactly one succeeds and the other gets the integrity error

### Requirement: A batch is all or nothing
A batch SHALL become visible to reads only once all of it has been written durably. A batch whose writing was
interrupted SHALL never be read as partly recorded.

#### Scenario: Interrupted write at the end of a segment
- **WHEN** a segment ends with an incomplete batch, because a write was interrupted
- **THEN** reads leave out the whole incomplete batch
- **AND** report a notice naming the segment and the fix

#### Scenario: Damage elsewhere in a segment
- **WHEN** a malformed line appears anywhere other than an incomplete batch at the end of a segment
- **THEN** reads fail with an error naming the file, the line and the fix

### Requirement: Notification IDs are local, dense and never renumbered
Notification IDs SHALL be assigned locally, per branch, from 1 with no gaps. Once issued on a branch, an ID SHALL
always name the same event there. Nothing that orders events SHALL be stored in a tracked file.

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

### Requirement: The local order rebuilds itself when events disappear
When an event named by the local order is no longer present (an event file removed by hand, or a reset), the
store SHALL rebuild the branch's order from the events present, and report it. Followers' positions recorded
against the old order SHALL be discarded, so their projections are rebuilt and nothing is skipped.

#### Scenario: An event file is removed
- **WHEN** an uncommitted event file is deleted, and the store is opened
- **THEN** the order is rebuilt without its events
- **AND** a notice says the order was rebuilt and why
- **AND** every follower starts again from the beginning

### Requirement: Followers' positions are local
A follower's position (the last notification it processed) SHALL be stored as a plain integer, outside git,
per branch.

#### Scenario: Positions are kept per branch
- **WHEN** a follower records its position on one branch, and the branch is switched
- **THEN** the follower's position on the other branch is its own

### Requirement: A forked stream is detected
A stream with more than one head SHALL be reported as forked. Loading its current state SHALL fail with an error
naming the stream, each head and the file it is in, and the fix. The store SHALL NOT pick a winner.

#### Scenario: Two branches append to one stream
- **WHEN** two branches each record version 5 of the same stream with different content, and are merged
- **THEN** loading that stream fails with an error naming both heads and their files
- **AND** the error says to settle the fork

#### Scenario: Appending to a forked stream
- **WHEN** an ordinary event is recorded to a forked stream
- **THEN** it is refused with the same error

### Requirement: A settling event ends a fork
A settling event SHALL name every head of a forked stream as its parents and carry the settled state. After it,
the stream SHALL have one head, and loading SHALL start from the settling event, never applying events from two
branches.

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

### Requirement: Uncommitted events from another branch are left out
An uncommitted segment made on a branch other than the current one SHALL be left out of every read on the current
branch, and reads SHALL report a notice naming the segment, its branch and the fix. Committed events SHALL be read
whatever branch made them.

#### Scenario: Untracked events travel with a branch switch
- **WHEN** events are recorded on branch `a` and not committed, and the user switches to branch `b`
- **THEN** reads on `b` leave those events out
- **AND** a notice names the segment and branch `a`

#### Scenario: Committed events from a merged branch are read
- **WHEN** a branch's committed events are merged into the current branch
- **THEN** reads include them

### Requirement: Events are never classified or dropped
The store SHALL keep every event that was recorded on the current branch. It SHALL NOT classify events as
abandoned or stashed. An edit and the edit that reverts it SHALL both stay recorded.

#### Scenario: An edit and its revert
- **WHEN** a stream is changed from 3 to 5, and then a later event changes it back to 3
- **THEN** its history reads 3, 5, 3

#### Scenario: Stash and pop
- **WHEN** events recorded around a `git stash` and `git stash pop` are read
- **THEN** every recorded event is present, in the order recorded

### Requirement: A missing parent is refused
An event that names a parent which is not present SHALL make reads of its stream fail with an error that names the
file holding the event, the missing parent, and the fix: restore the removed file, or remove the dependent one too.

#### Scenario: A parent's file was removed by hand
- **WHEN** the segment holding an event is deleted while a later event in another segment names it as a parent
- **THEN** reading that stream fails with an error naming the later event's file and the missing parent ID
- **AND** the fix says to restore the removed file or remove the dependent one

### Requirement: Writers wait for each other, bounded and announced
Recording SHALL be serialised across processes on one theatre. A writer that has to wait SHALL say what it is
waiting for and give up after a timeout, following the platform's lock rules. The lock SHALL NOT be a tracked file.

#### Scenario: Another process is recording
- **WHEN** a process records events while another process holds the store's write lock
- **THEN** the waiting process announces the wait, and fails with the lock timeout error if it doesn't end

#### Scenario: The lock file is not tracked
- **WHEN** events are recorded in a git theatre
- **THEN** `git status` shows no lock file

### Requirement: Store limits are named settings
Every limit the store uses (lock waits, the subscription poll interval) SHALL have its default in troupe's one
named place for defaults, and SHALL be overridable.

#### Scenario: The documentation lists the store's defaults
- **WHEN** the store's documentation is checked against the defaults
- **THEN** it lists exactly the defaults the store uses, with their values

### Requirement: Notices are structured data
Every non-failing condition a read reports SHALL be structured data with a stable code, the problem, the fix and,
where there is one, the path, defined once in the protocol.

#### Scenario: A notice matches the protocol schema
- **WHEN** any notice the store can produce is serialised
- **THEN** it validates against the protocol's notice schema
