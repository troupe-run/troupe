# Spec Delta

## ADDED Requirements

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
