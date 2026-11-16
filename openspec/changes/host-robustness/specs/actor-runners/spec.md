## MODIFIED Requirements

### Requirement: Protocol violations end the run
When a runner violates the contract, the host SHALL stop the runner and the outcome SHALL be `crashed` with an
error that names the violation. A malformed or ambiguous message SHALL be a violation, never quietly read with a
default. The violations are listed in the scenarios.

#### Scenario: Garbage on standard output
- **WHEN** a runner writes a line that is not JSON to standard output
- **THEN** the runner is stopped and the outcome is `crashed` with a protocol error naming the line's position

#### Scenario: Ambiguous JSON
- **WHEN** a runner sends a message with a duplicated key, or with `NaN` or `Infinity` as a value
- **THEN** it is a protocol violation, not read with either value

#### Scenario: Unknown method or response
- **WHEN** a runner sends a notification with a method the contract doesn't define, or a response to an id the
  host never sent
- **THEN** it is a protocol violation

#### Scenario: Answers that don't match the request
- **WHEN** a runner chooses a protocol version the host didn't offer, answers `run/start` with a different run id,
  or sends an event or transcript record for a different run id
- **THEN** it is a protocol violation

#### Scenario: Tool result without its call
- **WHEN** a runner sends a `tool_result` whose call id matches no earlier `tool_call` in the run
- **THEN** it is a protocol violation

#### Scenario: Invalid base64 transcript record
- **WHEN** a runner sends a transcript record with encoding `base64` that is not valid base64
- **THEN** it is a protocol violation, and nothing is written to the transcript for it

#### Scenario: A served model that is init's
- **WHEN** a runner's `init` names the model `m-1` and it later sends `served_model` with `model` `m-1`
- **THEN** it is a protocol violation naming the model

#### Scenario: A served model reported twice
- **WHEN** a runner sends `served_model` with `model` `m-2` twice in one run
- **THEN** the second is a protocol violation naming the model

#### Scenario: A lone surrogate in a message
- **WHEN** a runner sends a `run/transcript` record, or an event string, holding a lone surrogate (`"a\ud800b"`)
- **THEN** it is a protocol violation naming where in the message the string was, and the run ends `crashed` rather
  than failing without an outcome

#### Scenario: A valid line is never a violation because of masking
- **WHEN** the run's credential starts with `n`, and a runner sends a valid `run/transcript` line whose record is a
  newline written `\n` followed by the rest of the credential
- **THEN** it is not a protocol violation, and the run carries on

### Requirement: Oversized events are kept in full, out of line
When a run event is larger than the maximum event size, the host SHALL store the full event in the artifact store
and pass on in its place an event of the same `seq` and `type` that carries the original size and the stored
event's hash. The run SHALL continue.

#### Scenario: Huge tool result summary
- **WHEN** a runner sends a `tool_result` event larger than the maximum event size
- **THEN** the event passed on carries the size and a hash
- **AND** the stored artifact with that hash is the original event, byte for byte

#### Scenario: A huge event that holds the credential
- **WHEN** a runner sends an event larger than the maximum event size that holds the run's credential
- **THEN** the stored artifact is the event with `[credential]` in place of the credential, and holds no form of it

### Requirement: Any conforming runner can be checked
troupe SHALL provide a conformance suite that runs against any runner command and checks the runner against this
contract: the handshake, refusing a second `initialize`, `init` first and saying how the runner applies the effects,
a run start carrying effects and a scratch directory, sequence numbers, the result, cancel, shutdown, and exit on end
of input.

#### Scenario: Scripted runner conforms
- **WHEN** the conformance suite runs against the scripted runner
- **THEN** every check passes

#### Scenario: A runner that doesn't say how it applies the effects
- **WHEN** the suite runs against a runner whose `init` has no `effects`
- **THEN** the suite fails, naming the `init` event and `effects`

#### Scenario: A runner that answers a second initialize
- **WHEN** the suite runs against a runner that answers a second `initialize` with the handshake
- **THEN** the suite fails, naming the second `initialize` and `runner.already-initialized`

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
- **THEN** the stored line's record holds `[credential]` in place of the newline and the rest of the credential, the
  line is valid JSON, and no stored byte holds the credential
