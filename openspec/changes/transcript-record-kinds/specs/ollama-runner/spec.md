# Spec Delta

## MODIFIED Requirements

### Requirement: Every exchange with Ollama is a transcript record
The runner SHALL send as transcript records, before any event they lead to: the first request's body, then before each
later request each message it added to the conversation, each verbatim as sent, kind `sent`; and every line of every
streamed answer and every error body, verbatim, kind `received`. It SHALL NOT send a request's re-sent history again.

#### Scenario: A run with one tool call
- **WHEN** a run's first answer calls `Read` once and its second answer ends the run
- **THEN** its transcript is the first request's body, the first answer's lines, the assistant message and the `tool`
  message the runner added, and the second answer's lines, in that order

#### Scenario: Re-sent history
- **WHEN** a run makes three requests
- **THEN** the system and user messages appear in the transcript once, in the first request's body

#### Scenario: Each record's kind
- **WHEN** a run's first answer calls `Read` once and its second answer ends the run
- **THEN** the first request's body, the assistant message and the `tool` message are `sent` records, and every
  answer line is a `received` record

#### Scenario: An error body
- **WHEN** Ollama answers a request with status 400 and a body
- **THEN** the body is a `received` record

## ADDED Requirements

### Requirement: The Ollama runner uses transcript kinds
The runner SHALL accept `transcript-kinds` when troupe offers it, and otherwise SHALL send the same records without a
kind, as the contract says.

#### Scenario: troupe offers kinds
- **WHEN** troupe's `initialize` offers `transcript-kinds`
- **THEN** the runner's answer names `transcript-kinds`, and every transcript record it sends has a kind

#### Scenario: No capability offered
- **WHEN** `initialize` offers no capabilities
- **THEN** the runner answers with none, and sends the same transcript records with no kind
