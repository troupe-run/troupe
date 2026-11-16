## MODIFIED Requirements

### Requirement: troupe masks the credential in everything it keeps from a run
troupe SHALL replace the run's credential value with `[credential]` in every run event, transcript record and byte of
kept standard error it stores, and in any error or notice, before it is written or sent, including where the value
is split across reads.

#### Scenario: An echoed key in a log event
- **WHEN** a runner sends a `log` event whose message holds the credential
- **THEN** the recorded event's message holds `[credential]` in its place

#### Scenario: A key split across two reads of standard error
- **WHEN** a runner writes the credential to standard error in two writes, split in the middle
- **THEN** the kept standard error holds `[credential]`, and no part of the value that the split left on either side

#### Scenario: The JSON-escaped form
- **WHEN** a credential holds `/` and a runner sends it inside JSON text as `\/`
- **THEN** that form is masked too

#### Scenario: Masking never breaks a valid line
- **WHEN** a runner sends a line that is a valid message, whatever the run's credential and wherever its strings
  hold it
- **THEN** troupe reads the line as the message it is, and masks the strings in it, unless masking would make two keys
  of one object the same, which is a protocol violation rather than a value lost (spec: actor-runners)

#### Scenario: An escape before the rest of the credential
- **WHEN** the run's credential starts with `n`, and a runner sends a string holding a newline followed by the rest of
  the credential
- **THEN** troupe keeps the string with `[credential]` in place of the newline and the rest of the credential, so the
  JSON text it writes for the string doesn't hold the credential

#### Scenario: A key that holds the credential
- **WHEN** a runner sends a message with a duplicated key that holds the credential
- **THEN** the protocol error troupe records names the key with `[credential]` in its place
