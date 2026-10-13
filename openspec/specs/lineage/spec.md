# lineage Specification

## Purpose

Makes every event troupe records explain itself: who made it, through what, when, why, as part of which change,
with whose approval, and in what version-control state, so history can always be traced and trusted.

## Requirements

### Requirement: Every recorded event carries lineage
Every event troupe records SHALL carry lineage that validates against the protocol's lineage schema. An event
without valid lineage SHALL be refused before anything is written.

#### Scenario: Lineage is present
- **WHEN** troupe records an event
- **THEN** the recorded line's lineage validates against the lineage schema

#### Scenario: Missing lineage is refused
- **WHEN** a caller tries to record an event without lineage, or with lineage that fails the schema
- **THEN** recording fails with an error naming the invalid field
- **AND** nothing is written

### Requirement: The actor is never null
Lineage SHALL name an actor whose kind is `human`, `agent` or `unknown`. A `human` or `agent` actor SHALL have an
ID and the identity source that resolved it. `unknown` SHALL be explicit, for cases where nobody can be known (such
as a hand edit to a file), and SHALL NOT be used when identity resolution fails.

#### Scenario: A human actor
- **WHEN** a command run by a person records an event
- **THEN** the actor has kind `human`, an ID, and the source that resolved it

#### Scenario: An explicit unknown
- **WHEN** an event is recorded for a change whose author can't be known, such as a hand edit
- **THEN** the actor has kind `unknown`

#### Scenario: Null is never accepted
- **WHEN** lineage has a null or missing actor
- **THEN** recording fails

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

### Requirement: Lineage names each event's cause
Lineage SHALL name the event's cause, never null. An event a command records directly SHALL have a command cause
whose ID is its change ID. An event recorded in reaction to another SHALL have an event cause naming that event's
ID, and SHALL carry that event's change ID, so correlation follows a chain of reactions back to the command.

#### Scenario: A command's events
- **WHEN** a command records events directly
- **THEN** each has a command cause whose ID equals its change ID

#### Scenario: Reactions to an event
- **WHEN** a command records E1, and reacting to E1, E2, E3 and E4 are recorded
- **THEN** all four have E1's change ID
- **AND** E2, E3 and E4 each have an event cause naming E1's ID

#### Scenario: A reaction to a reaction
- **WHEN** E5 is recorded in reaction to E2, which was a reaction to E1
- **THEN** E5 has E1's change ID and an event cause naming E2

#### Scenario: A cause that names no event
- **WHEN** an event is recorded with an event cause naming an ID that isn't present
- **THEN** recording fails with an error naming the unknown cause
- **AND** nothing is written

#### Scenario: A command cause that disagrees with the change ID
- **WHEN** an event is recorded with a command cause whose ID differs from its change ID
- **THEN** recording fails, and nothing is written

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

### Requirement: Lineage is defined once, language-neutrally
The lineage shape SHALL be defined as JSON Schema in the protocol, and troupe's own types SHALL be checked against
it, so the two can't drift.

#### Scenario: Types and schema agree
- **WHEN** lineage built by troupe for each actor kind and each via is serialised
- **THEN** it validates against the lineage schema

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
