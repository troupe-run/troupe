## MODIFIED Requirements

### Requirement: The result record maps to the result event
A `result` record SHALL map to `result` with status `error` when `is_error` is true or its subtype isn't `success`,
and `ok` otherwise. It SHALL carry the record's text (or its subtype when it has none), turns, duration, the four
usage counters it has, and cost.

#### Scenario: An error under a success subtype
- **WHEN** a result record has subtype `success`, `is_error` true and result `Invalid API key`
- **THEN** the event is `result` with status `error` and message `Invalid API key`

#### Scenario: Usage counters
- **WHEN** a result record's usage has `input_tokens` 6, `output_tokens` 253, `cache_read_input_tokens` 42158 and
  `cache_creation_input_tokens` 5737
- **THEN** the result's usage is `inputTokens` 6, `outputTokens` 253, `cacheReadTokens` 42158 and
  `cacheWriteTokens` 5737

#### Scenario: A budget stop
- **WHEN** a result record has subtype `error_max_budget_usd` and no result text
- **THEN** the event is `result` with status `error`, message `error_max_budget_usd` and `reason` `budget`

## ADDED Requirements

### Requirement: An error result's reason comes from Claude Code's own fields
An `error` result's reason SHALL come from one table in the runner, never from the record's text. A subtype other than
`success` SHALL map by subtype: `error_max_turns` to `turn-limit`, `error_max_budget_usd` to `budget`,
`error_during_execution` to `engine`, any other to `other`. An API error SHALL map by its error code, then its HTTP
status.

#### Scenario: The turn limit
- **WHEN** a result record has subtype `error_max_turns`
- **THEN** the event is `result` with status `error` and `reason` `turn-limit`

#### Scenario: An error during execution
- **WHEN** a result record has subtype `error_during_execution`
- **THEN** the `result` has `reason` `engine`

#### Scenario: A subtype the table doesn't name
- **WHEN** a result record has subtype `error_widget`
- **THEN** the `result` has status `error` and `reason` `other`

### Requirement: An API error maps by its error code, then the last retry, then its status
For an `is_error` result record under subtype `success`, the reason SHALL be, in order: the last assistant record's
`error` code (`authentication_failed` to `authentication`, `billing_error` to `quota`, `rate_limit` to `rate-limit`,
`max_output_tokens` to `output-limit`); else the last `retry` since an assistant record without an error; else, for
`terminal_reason` `api_error`, its `api_error_status` as a retry maps it; else `other`.

#### Scenario: A rejected key
- **WHEN** the `is-error-success-subtype` fixture plays: its last assistant record has error `authentication_failed`
  and its result record `api_error_status` 401
- **THEN** the `result` has status `error` and `reason` `authentication`

#### Scenario: Rate limited until the retries ran out
- **WHEN** the `rate-limit-retries` fixture plays
- **THEN** the `result` has `reason` `rate-limit`

#### Scenario: Overloaded until the retries ran out
- **WHEN** the `server-retries` fixture plays
- **THEN** the `result` has `reason` `server`

#### Scenario: A refused connection Claude Code calls a server error
- **WHEN** the `network-retries` fixture plays: its retries have reason `network`, its last assistant record has error
  `server_error`, and its result record `api_error_status` null
- **THEN** the `result` has `reason` `network`

#### Scenario: An error code the table doesn't name, and no retry
- **WHEN** a run sent no retry, and its result record has `is_error` true, `terminal_reason` `api_error` and
  `api_error_status` 503, after an assistant record whose error is `widget_error`
- **THEN** the `result` has `reason` `server`

#### Scenario: An error with nothing to go on
- **WHEN** a result record has `is_error` true under subtype `success`, no retry came before it, no assistant record
  has an error, and its `terminal_reason` isn't `api_error`
- **THEN** the `result` has `reason` `other`

#### Scenario: An API error that recovered
- **WHEN** a run retries a rate limit, gets an assistant record with error `rate_limit`, then an assistant record
  without an error, and ends with a result record with `is_error` true and `terminal_reason` `completed`
- **THEN** the `result` has `reason` `other`
