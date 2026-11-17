## MODIFIED Requirements

### Requirement: troupe masks the credential in everything it keeps from a run
troupe SHALL replace the run's credential value with `[credential]` in every run event, transcript record and byte of
kept standard error it stores, and in any error or notice, before it is written or sent, including where the value
is split across reads. A transcript record SHALL stay valid in its own format: a record or line that is JSON text, or
a `data:` line holding JSON, is still that after masking, and none of its strings decodes to a form of the value.

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

#### Scenario: A record that is JSON, with an escape before the rest of the credential
- **WHEN** the run's credential is `nsecret-token-0123456789`, and a runner sends the transcript record
  `{"text":"key:\nsecret-token-0123456789"}` as text
- **THEN** troupe stores `{"text":"key:[credential]"}`, which is valid JSON, and keeps the rest of the record byte for
  byte

#### Scenario: Masking never breaks a record that is JSON
- **WHEN** a runner sends a transcript record that is JSON text, as text or as base64 of its UTF-8 bytes, whatever the
  run's credential and wherever and however the record's strings hold it
- **THEN** the stored record is valid JSON, and neither its text nor any string it decodes to holds a form of the
  credential outside `[credential]`

#### Scenario: A streamed answer's data line
- **WHEN** a runner sends the record `data: {"delta":"\nsecret-token-0123456789"}` and the credential is
  `nsecret-token-0123456789`
- **THEN** troupe stores `data: {"delta":"[credential]"}`

#### Scenario: A record of several JSON lines
- **WHEN** a runner sends one record holding several lines, each a JSON value, and one of them holds the credential
  after an escape
- **THEN** each stored line is still valid JSON, and only the line that held the credential changes

#### Scenario: The credential in a number
- **WHEN** the run's credential is all digits and a record that is JSON holds it in a number
- **THEN** that number is stored as the string `"[credential]"`, and the record is still valid JSON

#### Scenario: A credential made of JSON's own syntax
- **WHEN** the run's credential holds JSON syntax (such as `ab","cd`), and a record that is JSON holds it across two of
  its values, so no one string holds it
- **THEN** the smallest array or object (or other value) whose text holds it is stored as the string `"[credential]"`,
  the rest of the record byte for byte as sent, so the record is still valid JSON and holds no form of the credential

#### Scenario: A credential that reaches past every value
- **WHEN** a form of the credential in a record that is JSON reaches outside the line's JSON value, such as into a
  `data:` line's field name
- **THEN** that line's value is stored as `"[credential]"`, a `data:` line keeping its field name

#### Scenario: A record that isn't JSON
- **WHEN** a runner sends a text record that isn't JSON text and holds the credential
- **THEN** it is masked as a string is, with `[credential]` in place of the credential
