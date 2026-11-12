## MODIFIED Requirements

### Requirement: A run never carries on past its context window
Every request SHALL ask Ollama to refuse a conversation longer than the window rather than cut it, and never to drop
its start to make room (`truncate` and `shift` both `false`). When Ollama refuses a request in a run told `fail`, or
in a run told `compact` that has nothing left to remove, the run SHALL end with an `error` result holding Ollama's
message and naming the window and `contextLength`.

#### Scenario: Every request asks Ollama not to cut
- **WHEN** a run makes a request
- **THEN** the request's `truncate` and `shift` are both `false`

#### Scenario: A conversation that outgrows the window
- **WHEN** Ollama answers the second request of a run told `fail` with status 400 and a message saying the request
  exceeds the context size
- **THEN** no third request is made, and the `result` has status `error`, holding Ollama's message and naming the
  window and `contextLength`

#### Scenario: A cut answer
- **WHEN** an answer ends with `done_reason` `length`
- **THEN** the run ends with an `error` result, as a cut answer does

## ADDED Requirements

### Requirement: A run told compact removes old tool results before a request that wouldn't fit
In a run told `compact`, before each request whose estimated size is over a named share of the window, the runner
SHALL replace old tool results with the SDK's stub, oldest first, until the estimate is at or below a lower named
share, and SHALL send a `context` event before that request.

#### Scenario: A run that reads more than the window holds
- **WHEN** the `context-compacted` fixture plays: a run told `compact` with a small `contextLength` reads several
  files in turn
- **THEN** a request's oldest `tool` messages hold the SDK's stub in place of their output, and the run ends `ok`

#### Scenario: What is never removed
- **WHEN** a run told `compact` compacts its conversation
- **THEN** the `system` message, the first `user` message, every `assistant` message and the latest turn's `tool`
  messages are sent unchanged

#### Scenario: The event before the request
- **WHEN** a run told `compact` compacts its conversation
- **THEN** the runner sends one `context` event with `kind` `truncated`, `by` `runner`, and equal `messagesBefore`
  and `messagesAfter`, before the events of the next turn

#### Scenario: A run told fail
- **WHEN** a run told `fail` reaches the same size
- **THEN** no `tool` message is changed and no `context` event is sent

### Requirement: A run told compact compacts after a refusal and asks again
When Ollama refuses a request of a run told `compact` as longer than the window, the runner SHALL compact as before a
request and send the request again, which SHALL NOT count as a turn. When there is nothing left to remove, the run
SHALL end with `context-length`.

#### Scenario: The estimate was too low
- **WHEN** Ollama refuses a run's request as longer than the window, and old tool results remain
- **THEN** the runner sends a `context` event, sends the request again with those results stubbed, and the turn count
  is unchanged

#### Scenario: Nothing left to remove
- **WHEN** the `context-compaction-exhausted` fixture plays: Ollama refuses a request whose only tool results are the
  latest turn's
- **THEN** no `context` event is sent, and the run ends with `error` and `reason` `context-length`, saying compaction
  found nothing more to remove
