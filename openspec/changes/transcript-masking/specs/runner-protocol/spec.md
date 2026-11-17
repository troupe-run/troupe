## MODIFIED Requirements

### Requirement: The native transcript is a separate stream
The runner SHALL send its transcript as `run/transcript` notifications in order: its engine's native output, unchanged,
or with kinds, each record labelled. A runner that holds the conversation SHALL also send each message it adds to it,
verbatim, before the engine's output that follows, and SHALL NOT send re-sent history again. The host SHALL NOT
interpret records, apart from masking the run's credential, which reads a record that is JSON as JSON (spec: runs).

#### Scenario: Native records are kept verbatim
- **WHEN** a runner that doesn't use kinds sends transcript records, in a run with no credential or whose records
  don't hold it
- **THEN** the stored transcript contains exactly those records, in that order, byte for byte

#### Scenario: A runner with its own tool loop
- **WHEN** a runner that runs the tool loop itself sends a tool's output back to its engine
- **THEN** the message holding that output is a transcript record, before the engine's next output

#### Scenario: History sent again
- **WHEN** a runner sends its engine the whole conversation with each request
- **THEN** each message appears in the transcript once

#### Scenario: A record that holds the credential
- **WHEN** a runner sends a transcript record that holds the run's credential
- **THEN** the stored record is the same bytes with the credential masked, and still valid in its own format: a record
  that was JSON text is still JSON text, changed only in the strings that held the credential
