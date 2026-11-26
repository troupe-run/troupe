# Spec Delta

## MODIFIED Requirements

### Requirement: The actor is never null
Lineage SHALL name an actor whose kind is `human`, `agent`, `system` or `unknown`. A `human` or `agent` actor SHALL
have an ID and the identity source that resolved it. A `system` actor, troupe acting by itself, SHALL have an ID
naming troupe's component and the host it runs on, and no source. `unknown` SHALL be explicit, for cases where nobody
can be known (such as a hand edit to a file), and SHALL NOT be used when identity resolution fails.

#### Scenario: A human actor
- **WHEN** a command run by a person records an event
- **THEN** the actor has kind `human`, an ID, and the source that resolved it

#### Scenario: An explicit unknown
- **WHEN** an event is recorded for a change whose author can't be known, such as a hand edit
- **THEN** the actor has kind `unknown`

#### Scenario: Null is never accepted
- **WHEN** lineage has a null or missing actor
- **THEN** recording fails

#### Scenario: troupe acting by itself
- **WHEN** troupe approves a run's changes at a gate, on the host `build-01`
- **THEN** the acceptance's actor has kind `system` and the ID `core@build-01`, and no source

#### Scenario: A system actor with a source
- **WHEN** an event is recorded whose `system` actor has a source
- **THEN** recording fails with `events.lineage-invalid`, naming the actor, and nothing is written

## ADDED Requirements

### Requirement: Approvals come only from a gate
An event's `approvals` SHALL be empty unless the event keeps a run's work at a gate (spec: gates), and then SHALL
hold exactly one approval, whose actor is the event's own actor. An approval SHALL name its actor, a non-empty role
and an RFC 3339 time in UTC.

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
