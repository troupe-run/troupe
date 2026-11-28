## ADDED Requirements

### Requirement: Lineage names an event's performance
Lineage SHALL record `performance`, the id of the performance an event belongs to, on every event in a performance's
stream or in a run's stream, whatever records it. Every other event SHALL have no `performance`. An event that breaks
either rule SHALL be refused with `events.lineage-invalid`, naming the field, and nothing SHALL be written.

#### Scenario: A run's events
- **WHEN** a person performs `tester`
- **THEN** every event in the performance's stream and in the run's stream names the performance in its lineage

#### Scenario: Answering a gate
- **WHEN** a person approves a run's cue
- **THEN** the acceptance and the performance's end both name the run's performance in their lineage

#### Scenario: A config change
- **WHEN** a person runs `troupe config set`
- **THEN** the change's lineage has no `performance` field

#### Scenario: A run event without a performance is refused
- **WHEN** an event in a run's stream is recorded with lineage that has no `performance`
- **THEN** recording fails with `events.lineage-invalid`, naming `performance`, and nothing is written

#### Scenario: A config event with a performance is refused
- **WHEN** a config change is recorded with lineage that names a performance
- **THEN** recording fails with `events.lineage-invalid`, naming `performance`, and nothing is written

#### Scenario: A malformed performance is refused
- **WHEN** an event is recorded with lineage whose `performance` is `null`, or isn't a UUID in canonical lowercase
  form
- **THEN** recording fails with `events.lineage-invalid`, and nothing is written

### Requirement: The event schemas say which events name a performance
The protocol's schema for each run and performance event SHALL require `performance` in its lineage. The schema for
every other event troupe defines SHALL refuse it.

#### Scenario: A run event's schema
- **WHEN** a recorded run event's lineage has no `performance`
- **THEN** it fails its topic's schema

#### Scenario: A config event's schema
- **WHEN** a recorded config change's lineage names a performance
- **THEN** it fails its topic's schema
