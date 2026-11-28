## MODIFIED Requirements

### Requirement: Approvals come only from a gate
An event's `approvals` SHALL be empty unless the event lets a run's work through its gate (spec: gates): the run's
acceptance at a gate, or `Run.ChangesApproved` between a flow's steps. Such an event SHALL hold exactly one approval,
whose actor is the event's own actor. An approval SHALL name its actor, a non-empty role and an RFC 3339 time in UTC.

#### Scenario: A config change
- **WHEN** a person runs `troupe config set`
- **THEN** the change's lineage has `approvals` empty

#### Scenario: An accept without a gate
- **WHEN** a person accepts a failed run's pending changes
- **THEN** the acceptance's lineage has `approvals` empty

#### Scenario: An approval at a gate
- **WHEN** ada approves a run's cue
- **THEN** the acceptance's lineage has one approval, with ada as actor and role `director`, the same actor as the
  event's

#### Scenario: An approval between steps
- **WHEN** ada approves a flow's step waiting before its last
- **THEN** the step's `Run.ChangesApproved` has one approval, with ada as actor and role `director`
