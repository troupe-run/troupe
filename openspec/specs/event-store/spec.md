# event-store Specification

## Purpose

Capability: `cap:event-store`

Records troupe's events as append-only text that git can merge without conflicts, and reads them back in a stable
local order that meets the `eventsourcing` library's recorder contract, across branches, merges and forks.

## Requirements

### Requirement: Events are stored as mergeable text
Events SHALL be stored as UTF-8 JSON Lines, one event per line, in files under the theatre's tracked event
directory. A record SHALL be strict JSON, both written and read: no duplicate keys, no `NaN` or `Infinity`. Its
payload SHALL be readable JSON wherever it is JSON, not an opaque blob.

#### Scenario: A recorded event is one readable line
- **WHEN** an event troupe defines, whose payload is a JSON object, is recorded
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
Every limit the store uses (lock waits, the subscription's check interval, the interval of its fallback poll, and how
long stopping a subscription waits for its work to end) SHALL have its default in troupe's one named place for
defaults, and SHALL be overridable.

#### Scenario: The documentation lists the store's defaults
- **WHEN** the store's documentation is checked against the defaults
- **THEN** it lists exactly the defaults the store uses, with their values

### Requirement: Notices are structured data
Every non-failing condition a read reports SHALL be structured data with a stable code, the problem, the fix and,
where there is one, the path, defined once in the protocol.

#### Scenario: A notice matches the protocol schema
- **WHEN** any notice the store can produce is serialised
- **THEN** it validates against the protocol's notice schema

### Requirement: A subscription delivers other writers' events as they're recorded
A subscription to the event store SHALL deliver every new event, whoever wrote it (this process, another process, or
git bringing in segments), within a bound, without the subscriber or the store looking for it on a timer. Subscribers
SHALL see only the store port's subscription, never how a store learns of writes.

#### Scenario: Another process records events
- **WHEN** a process subscribes to the store, with `SUBSCRIBE_POLL_SECONDS` and `SUBSCRIBE_CHECK_SECONDS` set to 60 s,
  and another process records an event, five times, and then, while no delay so far is under 0.25 s, once more at a
  time for up to a 60 s allowance for a slow stretch
- **THEN** each event reaches the subscriber, the fastest of the delays, measured from when the writer's append
  returned, is under 0.25 s, and the median of the first five is within 0.25 s plus an allowance for a loaded machine

#### Scenario: The same guarantee through the port
- **WHEN** the installed store is loaded by name through the port with its defaults, and another process records an
  event while a subscriber waits, five times, and then, while no delay so far is under 0.25 s, once more at a time
  for up to a 60 s allowance for a slow stretch
- **THEN** each event reaches the subscriber, the fastest of the delays, measured from when the writer's call to
  record it returned, is under 0.25 s, and the median of the first five is within 0.25 s plus an allowance for a
  loaded machine

#### Scenario: The text store's first write creates its events directory
- **WHEN** a process subscribes to a text store that has no events yet, and another process records the first event
- **THEN** the event reaches the subscriber, though the events directory didn't exist when it subscribed

#### Scenario: The text store does no work while nothing is recorded
- **WHEN** a process subscribes to a text store, with `SUBSCRIBE_CHECK_SECONDS` set to 60 s, and nothing is recorded
  for 2 s
- **THEN** the store reads no segment in that time

### Requirement: A subscription that can only poll says so
When a store can't learn of other writers' events as they're recorded, its subscription SHALL find them by looking
every `SUBSCRIBE_POLL_SECONDS` instead, and while it does, the store's notices SHALL include
`events.subscription-polling`, naming the reason, the fix and, where there is one, the path. It SHALL never poll
silently.

#### Scenario: The text store's directory can't be watched
- **WHEN** a process subscribes to a text store and the platform refuses to watch its events directory
- **THEN** the store's notices include `events.subscription-polling`, with the reason `watch-refused`, the directory
  and the platform's reason
- **AND** before each look, the subscription waits once, for `SUBSCRIBE_POLL_SECONDS`
- **AND** when another process records an event, five times, each event reaches the subscriber, delivered no later
  than the first look the subscription started after the writer's append returned
- **AND** the median delay of the five, measured from when the writer's append returned, is within
  `SUBSCRIBE_POLL_SECONDS` plus an allowance for a loaded machine

#### Scenario: The notice lasts as long as the polling
- **WHEN** the store's notices are read twice while its subscription is polling
- **THEN** both include `events.subscription-polling`

### Requirement: A subscription that finds it missed an event says so
Every `SUBSCRIBE_CHECK_SECONDS` while it has subscribers, the store SHALL look for other writers' events itself. If it
finds one that its notification didn't deliver in that interval, it SHALL deliver it, change to polling, and announce
`events.subscription-polling`, saying an event was missed.

#### Scenario: A text store whose watch never reports
- **WHEN** a process subscribes to a text store through a watch that is set up but never reports, and another process
  records an event
- **THEN** the event reaches the subscriber within `SUBSCRIBE_CHECK_SECONDS`, plus an allowance for the time to read
  it on a loaded machine
- **AND** the store's notices include `events.subscription-polling`, with the reason `watch-missed-write`
- **AND** before each look it then makes, the subscription waits once, for `SUBSCRIBE_POLL_SECONDS`
- **AND** when another process then records an event, five times, each event reaches the subscriber, delivered no
  later than the first look the subscription started after the writer's append returned
- **AND** the median delay of the five, measured from when the writer's append returned, is within
  `SUBSCRIBE_POLL_SECONDS` plus an allowance for a loaded machine

### Requirement: A stopped subscription leaves the store alone
When stopping a subscription returns, the store SHALL have finished all work done for that subscription. It SHALL
not read the store, write any file under the theatre, or deliver to any listener for that subscription afterwards.
Anything it watched the file system with SHALL be released. This holds whatever the subscription was doing when it
was stopped, including if it hadn't started yet.

#### Scenario: A subscription stopped before its first delivery
- **WHEN** a process subscribes to a text store whose order needs rebuilding, and stops the subscription before the
  subscription has delivered anything
- **THEN** when the stop returns, the store's subscription work has ended
- **AND** no file under the theatre is created, changed or removed in the second after the stop returned

#### Scenario: A subscription stopped while it delivers
- **WHEN** a subscription is delivering, and the subscriber stops it before that delivery is finished
- **THEN** the stop returns only after the delivery has finished, and the store's subscription work has then ended

#### Scenario: The library's subscription case cleans up
- **WHEN** the event-sourcing library's subscription case runs against the text store, and its temporary theatre is
  deleted as soon as the case ends
- **THEN** the deletion succeeds, and no exception is raised in any other thread

### Requirement: Stopping a subscription never waits silently or indefinitely
Waiting for a subscription's work to end SHALL be bounded by `SUBSCRIBE_STOP_TIMEOUT_SECONDS`. If the wait lasts the
store's lock-announce interval, it SHALL be announced. If it reaches the bound, stopping SHALL fail with
`events.subscription-not-stopped`, naming the events directory, how long it waited and the fix. It SHALL never
return as though the subscription had stopped.

#### Scenario: Subscription work that doesn't end
- **WHEN** a subscription's work doesn't end once it is stopped, with `SUBSCRIBE_STOP_TIMEOUT_SECONDS` set to 0.5 s
- **THEN** the wait is announced once, naming the events directory
- **AND** stopping fails with `events.subscription-not-stopped` after between 0.5 s and 0.5 s plus an allowance for a
  loaded machine
- **AND** the error validates against the protocol's error schema

### Requirement: Each event troupe defines has a payload schema
Every event troupe defines SHALL have a closed JSON Schema for its payload in `protocol/`, named by the event's
topic, including the fields the event-sourcing library adds. The event-record schema SHALL choose the payload schema
by topic, and an inline payload whose topic troupe doesn't define SHALL NOT validate.

#### Scenario: A run's events validate by topic
- **WHEN** a run is recorded and its segment lines are read
- **THEN** each line's payload validates against the schema for its topic: the run's start, a reported run event or
  the run's end

#### Scenario: An unknown topic
- **WHEN** a segment line holds an inline payload under a topic troupe doesn't define
- **THEN** it doesn't validate against the protocol's event-record schema

#### Scenario: Every topic has a schema
- **WHEN** troupe declares a topic its aggregates record and the protocol has no payload schema for it, or the
  protocol has a payload schema for a topic troupe doesn't declare
- **THEN** the build fails, naming the topic

### Requirement: A segment header leaves out a branch it doesn't have
A segment's header SHALL name the branch the segment was written on, and SHALL leave `branch` out when it was written
with no branch (a detached HEAD, or an adapter without branches). A header whose `branch` is `null` or empty SHALL be
read as a malformed record.

#### Scenario: A segment written on a detached HEAD
- **WHEN** a session records an event in a git theatre whose HEAD is detached
- **THEN** its segment's header has a session and a VCS adapter, and no `branch`

#### Scenario: A null branch in a header
- **WHEN** a segment's header line has `"branch": null`
- **THEN** reading it fails with `events.malformed-record`, naming the file and line

#### Scenario: An uncommitted segment with no branch
- **WHEN** reads on the current branch leave out an uncommitted segment that was written with no branch
- **THEN** the `events.other-branch` notice names the segment, and its details have no `branch`

### Requirement: No troupe event payload holds a null
No payload troupe records SHALL hold a `null` at any depth. A field with nothing to say SHALL be left out, and its
payload schema SHALL say what its absence means.

#### Scenario: A run that never started
- **WHEN** a run whose runner couldn't be started is recorded, and its segment lines are read
- **THEN** no payload contains `null`, and each validates against its topic's schema

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

### Requirement: A segment header names the protocol that wrote it
A segment's header SHALL name the protocol version of the troupe that wrote the segment. A header without it, or with
a value that isn't a version, SHALL be read as a malformed record.

#### Scenario: A new segment
- **WHEN** a session records its first event with a troupe that carries protocol 0.2.0
- **THEN** its segment's header has `"protocol": "0.2.0"`, alongside its session and VCS adapter

#### Scenario: A header with no protocol
- **WHEN** a segment's header line has no `protocol`
- **THEN** reading it fails with `events.malformed-record`, naming the file and line

#### Scenario: A header the schema checks
- **WHEN** a segment header line without `protocol` is validated against the protocol's event-record schema
- **THEN** it doesn't validate
