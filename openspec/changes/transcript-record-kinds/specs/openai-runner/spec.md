# Spec Delta

## MODIFIED Requirements

### Requirement: The transcript is the exchange with the service
The runner SHALL send, as `run/transcript` records in the order they happen, each request body as sent, kind `sent`;
each line of each response's stream unchanged, its `event:` lines included, and each error response's body, kind
`received`; and, kind `note`, each response's status with the response headers the runner names in one place, and
each stream it abandons. A `sent` or `received` record SHALL be the bytes themselves. No request header SHALL be
recorded.

#### Scenario: A run's transcript
- **WHEN** a run makes one request and gets one streamed response
- **THEN** its transcript holds a `sent` record that is the request body, then a `note` of the response's status,
  then one `received` record for each line of the response's stream, in order

#### Scenario: No request header
- **WHEN** any transcript record is read
- **THEN** none holds a request header

#### Scenario: An error response
- **WHEN** a request is answered 429 with a JSON body
- **THEN** the transcript holds a `note` naming status 429 and the kept headers, then a `received` record that is the
  body, byte for byte

#### Scenario: A broken stream
- **WHEN** a response's stream breaks off and the runner abandons it
- **THEN** the transcript holds a `note` saying why, after the stream's last `received` line

## ADDED Requirements

### Requirement: The OpenAI runner uses transcript kinds
The runner SHALL accept `transcript-kinds` when troupe offers it, and otherwise SHALL send the same records without a
kind, as the contract says.

#### Scenario: troupe offers kinds
- **WHEN** troupe's `initialize` offers `transcript-kinds`
- **THEN** the runner's answer names `transcript-kinds`, and every transcript record it sends has a kind

#### Scenario: No capability offered
- **WHEN** `initialize` offers no capabilities
- **THEN** the runner answers with none, and sends the same transcript records with no kind
