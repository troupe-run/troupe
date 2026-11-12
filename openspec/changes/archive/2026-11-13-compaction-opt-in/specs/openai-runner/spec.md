## ADDED Requirements

### Requirement: A run told compact compacts after a context-length refusal and asks again
When the service refuses a request of a run told `compact` with `context_length_exceeded`, the runner SHALL replace
old `function_call_output`s with the SDK's stub, oldest first, until the estimate is at or below a named share of the
last accepted request's input tokens. It SHALL then send a `context` event and the request again, not counted as a
turn.

#### Scenario: A refused request, then success
- **WHEN** a run told `compact` has its third request refused with `context_length_exceeded`
- **THEN** the runner sends a `context` event with `kind` `truncated` and `by` `runner`, then sends the third request
  again with the oldest outputs stubbed, and the run's turn count and token usage are unchanged by the refusal

#### Scenario: What is never removed
- **WHEN** a run told `compact` compacts its conversation
- **THEN** the `instructions`, the first `user` message, every output item of the service's replies (including
  `reasoning` items and `function_call`s) and the latest turn's `function_call_output`s are sent unchanged

#### Scenario: Nothing left to remove
- **WHEN** a run told `compact` is refused with `context_length_exceeded` and its only outputs are the latest turn's
- **THEN** no `context` event is sent, and the run ends with `error` and `reason` `context-length`, saying compaction
  found nothing more to remove

#### Scenario: A run told fail
- **WHEN** a run told `fail` has a request refused with `context_length_exceeded`
- **THEN** the request isn't sent again, and the run ends with `error` and `reason` `context-length`
