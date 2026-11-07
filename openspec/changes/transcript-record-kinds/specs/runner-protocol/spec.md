# Spec Delta

## MODIFIED Requirements

### Requirement: The native transcript is a separate stream
The runner SHALL send its engine's native output, record by record and unchanged, as `run/transcript`
notifications in the order produced. A runner that holds the conversation itself SHALL also send each message it adds
to the conversation, verbatim as it sent it, before the engine's output that follows it, and SHALL NOT send re-sent
history again. Transcript records SHALL NOT be interpreted by the host, apart from masking the
run's credential (spec: runs).

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
- **THEN** the stored record is the same bytes with the credential masked

## ADDED Requirements

### Requirement: A transcript record can say what kind it is
`run/transcript` SHALL accept an optional `kind`: `sent` for what the runner sent its engine, verbatim; `received`
for what the engine sent back, verbatim; `note` for the runner's own record about the exchange. A record without a
kind is the engine's native output. Any other kind SHALL NOT validate against the contract's schema.

#### Scenario: A request body
- **WHEN** a runner that drives an API sends the body of a request it made as a transcript record
- **THEN** the record's kind is `sent` and the record is the body as sent

#### Scenario: An unknown kind
- **WHEN** a `run/transcript` notification carries kind `request`
- **THEN** it does not validate against the contract's schema

### Requirement: The transcript-kinds capability
The host SHALL offer the capability `transcript-kinds` at `initialize`. Capability names SHALL be a closed list in the
contract's schema, and `transcript-kinds` is its only entry. A runner MAY accept it; a runner that has nothing to
label, such as one that passes on an engine's native output, SHALL NOT.

#### Scenario: troupe's offer
- **WHEN** troupe sends `initialize`
- **THEN** its capabilities are `transcript-kinds`

#### Scenario: An unknown capability name
- **WHEN** an `initialize` answer names the capability `widgets`
- **THEN** it does not validate against the contract's schema

### Requirement: Kinds are all or nothing in a run
A runner that accepted `transcript-kinds` SHALL give every transcript record of its run a kind, and one that didn't
SHALL give none. The host SHALL treat a record that breaks this as a protocol violation and store nothing for it.

#### Scenario: A record without a kind in a run that uses kinds
- **WHEN** a runner that accepted `transcript-kinds` sends a transcript record with no kind
- **THEN** the host treats it as a protocol violation, and the record isn't stored

#### Scenario: A kind in a run that doesn't use kinds
- **WHEN** a runner that didn't accept `transcript-kinds` sends a transcript record with kind `received`
- **THEN** the host treats it as a protocol violation, and the record isn't stored

### Requirement: A runner offered no kinds sends its records without them
A runner that would label its records, offered no `transcript-kinds` (a host from before the capability), SHALL send
the same records, in the same order, without a kind.

#### Scenario: An older host
- **WHEN** a runner that uses kinds is offered no capabilities
- **THEN** it answers with no capabilities, and its transcript records are the same records without a kind
