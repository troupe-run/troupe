# Spec Delta

## ADDED Requirements

### Requirement: A run that uses kinds stores each record with its kind
When the runner accepted `transcript-kinds`, the host SHALL store each transcript line as a JSON object holding the
record's `kind` and its masked `record`, with `encoding` `base64` exactly when the runner sent the record as base64.
Each line SHALL validate against the protocol's stored transcript record schema.

#### Scenario: A sent record and a received record
- **WHEN** a runner that accepted `transcript-kinds` sends a `sent` record `{"model":"m"}` and then a `received`
  record `data: {}`
- **THEN** the stored transcript is two lines, `{"kind":"sent","record":"{\"model\":\"m\"}"}` and
  `{"kind":"received","record":"data: {}"}`, each followed by `\n`

#### Scenario: A record that isn't text
- **WHEN** a runner that accepted `transcript-kinds` sends a `received` record with encoding `base64`
- **THEN** its stored line has kind `received`, encoding `base64`, and the base64 of the record's bytes after masking

#### Scenario: The credential in a record that uses kinds
- **WHEN** a runner that accepted `transcript-kinds` sends a record holding the run's credential
- **THEN** the stored line's record holds `[credential]` in its place, and the line is still valid JSON

#### Scenario: An escape that would complete the credential
- **WHEN** the run's credential starts with `n`, and a runner that accepted `transcript-kinds` sends a record holding a
  newline (written `\u000a`) followed by the rest of the credential
- **THEN** the stored line holds that record as base64 of its bytes, and no stored byte holds the credential

### Requirement: A run without kinds is stored as before
When the runner didn't accept `transcript-kinds`, the host SHALL store each record's bytes, after masking, followed by
`\n`, with nothing added.

#### Scenario: A Claude Code run
- **WHEN** the Claude Code runner, which accepts no capability, sends its stream-json lines
- **THEN** the stored transcript is those lines, each followed by `\n`, byte for byte

### Requirement: The transcript limit counts what is stored
The maximum transcript size SHALL be measured against the bytes the host stores, the framing included.

#### Scenario: Framing passes the limit
- **WHEN** a run that uses kinds sends records whose own bytes are under the maximum transcript size but whose stored
  lines pass it
- **THEN** the run is cancelled and the outcome is `failed` with an error naming the limit
