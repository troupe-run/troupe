## MODIFIED Requirements

### Requirement: Lineage says how, when and why
Lineage SHALL record `via` (the surface the event came through, such as `cli`, `file` or `runner`), the time in UTC,
the reason (left out when none was given, never recorded as null), the change ID (the correlation ID shared by every
event that follows from one command, the sweep before a command counting as a command of its own), the cause, and the
approvals given (an empty list when none).

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

#### Scenario: A sweep's changes have a change ID of their own
- **WHEN** a command's sweep records a hand edit, and the command then records its own change
- **THEN** the hand edit's change ID differs from the command's
- **AND** every change that one sweep records shares one change ID
