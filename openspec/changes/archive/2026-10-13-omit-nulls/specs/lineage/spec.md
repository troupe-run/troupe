# Spec Delta

## MODIFIED Requirements

### Requirement: Lineage says how, when and why
Lineage SHALL record `via` (the surface the event came through, such as `cli`, `file` or `runner`), the time in UTC,
the reason (left out when none was given, never recorded as null), the change ID (the correlation ID shared by every
event that follows from one command), the cause, and the approvals given (an empty list when none).

#### Scenario: Events from one command share a change ID
- **WHEN** one command records several events
- **THEN** every one has the same change ID
- **AND** a different command's events have a different change ID

#### Scenario: Time is UTC
- **WHEN** an event is recorded
- **THEN** its lineage time is an RFC 3339 timestamp in UTC

#### Scenario: No reason given
- **WHEN** a command records an event without a reason
- **THEN** its lineage has no `reason` field

#### Scenario: A null reason is refused
- **WHEN** an event is recorded with lineage whose `reason` is `null`
- **THEN** recording fails with `events.lineage-invalid`, and nothing is written

### Requirement: Lineage records the version-control state
Lineage SHALL record the VCS adapter in use, the branch (left out when HEAD is detached or the adapter has no
branches; the adapter tells which) and HEAD (left out when there is no commit). An event made from a file SHALL also
record the file's theatre-relative path and the content hashes of the file before and after the change (each left
out for a file that didn't exist, or no longer exists). An event not made from a file SHALL have no `source`. None
of these SHALL be recorded as null.

#### Scenario: An event recorded on a git branch
- **WHEN** an event is recorded in a git theatre on branch `main`
- **THEN** its lineage names the git adapter, branch `main` and the current HEAD commit

#### Scenario: An event made from a file edit
- **WHEN** an event records a change to a file
- **THEN** its lineage holds the file's path relative to the theatre, with `/` separators, and the before and
  after content hashes

#### Scenario: An event made from a new file
- **WHEN** an event records a file that didn't exist before
- **THEN** its lineage's `source` has the path and `after`, and no `before`

#### Scenario: A theatre with no version control
- **WHEN** an event is recorded in a theatre using the plain filesystem adapter
- **THEN** its lineage names that adapter, with no `branch` and no `head`

#### Scenario: A detached HEAD
- **WHEN** an event is recorded in a git theatre whose HEAD is detached
- **THEN** its lineage names the git adapter and HEAD, with no `branch`

#### Scenario: A null in the version-control state is refused
- **WHEN** an event is recorded with lineage whose `vcs.branch`, `vcs.head`, `vcs.source`, `vcs.source.before` or
  `vcs.source.after` is `null`
- **THEN** recording fails with `events.lineage-invalid`, and nothing is written

## ADDED Requirements

### Requirement: Lineage records the stage an event's run was on
Lineage SHALL record `stage` for an event recorded on a stage: the stage's name and whether the actor's effects were
`enforced` or `unenforced`. An event recorded outside a stage SHALL have no `stage`. An unenforced stage SHALL name
the policy setting, and its source, that allowed it, in `allowedBy`; an enforced one SHALL have no `allowedBy`.

#### Scenario: An event recorded outside a stage
- **WHEN** a command records an event that isn't part of a run
- **THEN** its lineage has no `stage` field

#### Scenario: A run on the local stage
- **WHEN** a run on the local stage, allowed by `allow_unenforced_local_stage` from `env`, records an event
- **THEN** its lineage's `stage` names `local`, effects `unenforced`, and the setting and source that allowed it

#### Scenario: An enforced stage
- **WHEN** a run on a stage that enforces its effects records an event
- **THEN** its lineage's `stage` names the stage and effects `enforced`, with no `allowedBy`

#### Scenario: Unenforced without an allowance is refused
- **WHEN** an event is recorded with a `stage` whose effects are `unenforced` and that names nothing that allowed it
- **THEN** recording fails with `events.lineage-invalid`, and nothing is written

#### Scenario: A null stage is refused
- **WHEN** an event is recorded with lineage whose `stage` or `stage.allowedBy` is `null`
- **THEN** recording fails with `events.lineage-invalid`, and nothing is written

## REMOVED Requirements

### Requirement: Lineage records the stage and whether effects were enforced
**Reason**: It required `stage` on every event, recorded as `null` outside a stage, and its "Stage is never missing"
scenario refused an event without one. Under the protocol's null rule an event outside a stage has no `stage`, so
the requirement is reversed rather than amended.
**Migration**: Replaced by "Lineage records the stage an event's run was on". Producers leave `stage` out for an
event recorded outside a stage, and readers treat its absence as "not on a stage". Segments written before this
change aren't read (design D7).
