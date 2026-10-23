## ADDED Requirements

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
