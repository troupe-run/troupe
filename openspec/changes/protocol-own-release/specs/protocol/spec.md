## ADDED Requirements

### Requirement: troupe records the protocol version it carries
The troupe package SHALL record the protocol version of its copy of `protocol/schemas/`: the protocol release that
copy belongs to. Core SHALL read it from that record, wherever it reports or writes the protocol version, and from
nowhere else. A record that is missing or isn't a version SHALL be an error naming the file, never a default.

#### Scenario: An installed troupe
- **WHEN** troupe is installed from a built wheel, with no checkout of this repository
- **THEN** it reports the protocol version it was built with, without a network connection

#### Scenario: A malformed record
- **WHEN** the recorded protocol version is `"next"`
- **THEN** reading it fails, naming the file and that it must be a version such as `0.2.0`

#### Scenario: Before the protocol's first release
- **WHEN** the protocol has never been released
- **THEN** the recorded version is `0.0.0`
