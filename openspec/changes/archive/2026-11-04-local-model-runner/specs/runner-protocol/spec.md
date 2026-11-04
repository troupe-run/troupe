# Spec Delta

## MODIFIED Requirements

### Requirement: Retries are reported as they happen
When the actor's engine retries (for example, an API call), or the runner retries a request to its engine itself,
the runner SHALL send a `retry` event carrying the attempt, the maximum attempts when known, the delay before the next
attempt, and a reason from a fixed list: `authentication`, `rate-limit`, `network`, `server` or `other`.

#### Scenario: Authentication retry
- **WHEN** the engine retries because authentication failed
- **THEN** the runner sends a `retry` event with reason `authentication`

#### Scenario: A runner's own retry
- **WHEN** a runner that calls its engine's API itself makes a request again because the connection dropped
- **THEN** it sends a `retry` event with reason `network` before the new attempt

### Requirement: The native transcript is a separate stream
The runner SHALL send its engine's native output, record by record and unchanged, as `run/transcript`
notifications in the order produced. A runner that holds the conversation itself SHALL also send each message it adds
to the conversation, verbatim as it sent it, before the engine's output that follows it, and SHALL NOT send re-sent
history again. Transcript records SHALL NOT be interpreted by the host.

#### Scenario: Native records are kept verbatim
- **WHEN** a runner sends transcript records
- **THEN** the stored transcript contains exactly those records, in that order, byte for byte

#### Scenario: A runner with its own tool loop
- **WHEN** a runner that runs the tool loop itself sends a tool's output back to its engine
- **THEN** the message holding that output is a transcript record, before the engine's next output

#### Scenario: History sent again
- **WHEN** a runner sends its engine the whole conversation with each request
- **THEN** each message appears in the transcript once

## ADDED Requirements

### Requirement: A runner refuses a platform it can't run on
A runner that finds, before it acknowledges `run/start`, that what it runs on doesn't meet a requirement of its own
SHALL refuse `run/start` with the contract's `runner.requirement-unmet`. Its details SHALL name the requirement and
what's wanted, and what was found when the runner could find it.

#### Scenario: An engine too old
- **WHEN** a runner that needs its engine at version 0.12.6 or later finds version 0.12.5
- **THEN** it refuses `run/start` with `runner.requirement-unmet`, whose details name the engine, `>= 0.12.6` and
  `0.12.5`, and the error validates against the contract alone

#### Scenario: Nothing found
- **WHEN** a runner can't find out what it requires, such as a version its engine didn't report
- **THEN** its `runner.requirement-unmet` details have no `found`
