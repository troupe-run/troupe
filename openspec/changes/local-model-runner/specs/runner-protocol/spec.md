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
