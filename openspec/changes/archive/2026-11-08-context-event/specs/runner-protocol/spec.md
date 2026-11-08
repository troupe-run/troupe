## MODIFIED Requirements

### Requirement: Run events are notifications with a sequence number
The runner SHALL report the run as `run/event` notifications. Each event SHALL carry the run id, a `seq` that
starts at 0 and increases by one with each event, and a `type`. The event types SHALL be `init`, `turn`,
`tool_call`, `tool_result`, `retry`, `context`, `log`, `served_model` and `result`.

#### Scenario: Events are numbered without gaps
- **WHEN** a runner sends events for a run
- **THEN** their `seq` values are 0, 1, 2 and so on, without gaps or repeats

#### Scenario: Gap in the sequence
- **WHEN** the host receives an event whose `seq` is not one more than the previous event's
- **THEN** the host treats it as a protocol violation

## ADDED Requirements

### Requirement: Content lost while the run carries on is a context event
When the actor's engine, or the runner itself, compacts or drops content of the run's conversation and the run
carries on, the runner SHALL send a `context` event at that point, before any event that follows from the reduced
conversation. A `context` event SHALL NOT end the run. A loss that ends the run SHALL be reported by the run's
`result`, not by a `context` event.

#### Scenario: The engine compacts and carries on
- **WHEN** a runner's engine summarises the earlier conversation and goes on working
- **THEN** the runner sends a `context` event before the events of the engine's next turn
- **AND** the run goes on to send further events and a `result`

#### Scenario: A context event after the result
- **WHEN** a runner sends a `context` event after its `result` event
- **THEN** the host treats it as a protocol violation

#### Scenario: A context event before init
- **WHEN** a runner's first run event is a `context` event
- **THEN** the host treats it as a protocol violation

### Requirement: A context event names what happened from a closed list
A `context` event SHALL carry a `kind`: `compacted` when earlier content was summarised, `truncated` when earlier
content was dropped outright, or `other` for a loss neither names. It SHALL carry a `message` saying what happened
in words, which for `other` SHALL name what was lost. A runner SHALL NOT send a kind outside the list.

#### Scenario: Earlier turns summarised
- **WHEN** an engine replaces the earlier conversation with a summary of it
- **THEN** the runner's `context` event has `kind` `compacted`

#### Scenario: Oldest messages dropped
- **WHEN** an engine drops the oldest messages of the conversation without summarising them
- **THEN** the runner's `context` event has `kind` `truncated`

#### Scenario: A kind of the runner's own
- **WHEN** a `context` event's `kind` is `pruned`
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation

#### Scenario: A context event without a message
- **WHEN** a `context` event has no `message`
- **THEN** it does not validate against the contract's schema

### Requirement: A context event says who lost the content
A `context` event SHALL carry `by`: `engine` when the engine reduced the conversation on its own, or `runner` when
the runner reduced the conversation it holds and sends to its engine.

#### Scenario: Claude Code compacts
- **WHEN** a runner reports that the engine it drives compacted its own conversation
- **THEN** the `context` event's `by` is `engine`

#### Scenario: The runner compacts its own conversation
- **WHEN** a runner that holds the conversation itself summarises old tool output before its next request
- **THEN** the `context` event's `by` is `runner`

### Requirement: A context event carries the amounts that are known
A `context` event MAY carry `tokensBefore`, `tokensAfter`, `messagesBefore` and `messagesAfter`, each a count of zero
or more of the conversation's tokens or messages before and after the loss. Each SHALL be present only when the
engine or runner knows it, and SHALL otherwise be left out, never sent as null.

#### Scenario: Only the size before is known
- **WHEN** an engine reports how many tokens the conversation held before it compacted, and nothing more
- **THEN** the `context` event carries `tokensBefore` and none of the other three counts

#### Scenario: A runner that counts its own conversation
- **WHEN** a runner that holds the conversation drops messages from it
- **THEN** its `context` event carries `messagesBefore` and `messagesAfter`

#### Scenario: A null count
- **WHEN** a `context` event carries `"tokensAfter": null`
- **THEN** it does not validate against the contract's schema

#### Scenario: A count the contract doesn't define
- **WHEN** a `context` event carries a field the contract doesn't define, such as `turnsBefore`
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation
