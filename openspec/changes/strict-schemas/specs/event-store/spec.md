# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
