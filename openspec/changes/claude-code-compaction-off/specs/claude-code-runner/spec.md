## ADDED Requirements

### Requirement: Claude Code's automatic compaction is off
The runner SHALL turn off Claude Code's automatic compaction on every run, whatever its options, by setting
`autoCompactEnabled` to `false` in the settings file it gives Claude Code with `--settings`. A run whose context fills
then ends with an error result rather than carrying on from a summary of its earlier turns.

#### Scenario: A run with no options
- **WHEN** a run starts with no options
- **THEN** the settings file Claude Code is given with `--settings` holds `autoCompactEnabled` `false`

#### Scenario: A run that loads project settings
- **WHEN** a run starts with `settingSources` `["project"]`
- **THEN** the settings file Claude Code is given with `--settings` still holds `autoCompactEnabled` `false`

### Requirement: Claude Code's context limit maps to context-length
An `is_error` result record whose `terminal_reason` is `prompt_too_long` (the API refused the request as too long) or
`blocking_limit` (Claude Code stopped before sending a request that would not fit) SHALL map to a `result` with
status `error` and `reason` `context-length`, whatever error code or retry came before it.

#### Scenario: The API refuses a request as too long
- **WHEN** the `context-limit-refused` fixture plays: its last assistant record has error `invalid_request` and its
  result record `terminal_reason` `prompt_too_long` and `api_error_status` 400
- **THEN** the `result` has status `error` and `reason` `context-length`

#### Scenario: Claude Code stops before the request
- **WHEN** the `context-limit-blocked` fixture plays: its result record has `terminal_reason` `blocking_limit` and no
  `api_error_status`
- **THEN** the `result` has status `error` and `reason` `context-length`

#### Scenario: A context limit after a rate limit retry
- **WHEN** a run retries a rate limit, and then ends with a result record with `is_error` true and `terminal_reason`
  `prompt_too_long`
- **THEN** the `result` has `reason` `context-length`

## MODIFIED Requirements

### Requirement: An API error maps by its error code, then the last retry, then its status
For an `is_error` result record under subtype `success` that isn't a context limit, the reason SHALL be, in order: the
last assistant record's `error` code (`authentication_failed` to `authentication`, `billing_error` to `quota`,
`rate_limit` to `rate-limit`, `max_output_tokens` to `output-limit`); else the last `retry` since an assistant record
without an error; else, for `terminal_reason` `api_error`, its `api_error_status` as a retry maps it; else `other`.

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

### Requirement: Fixtures pair real Claude Code output with protocol events
The plugin SHALL include fixtures captured from real Claude Code runs. Each SHALL pair the native lines, unchanged
except for scrubbing, with the events they map to, and record its provenance. They SHALL cover the `success` subtype
with `is_error`, retries for authentication, network, server and rate limits, a run with no `result`, a success
with tools, and a context limit both refused by the API and reached before a request.

#### Scenario: The mapping reproduces each fixture
- **WHEN** each fixture's native lines are mapped by the runner
- **THEN** the transcript records and events are exactly the fixture's, in order

#### Scenario: Fixtures replay through the contract
- **WHEN** each fixture is replayed by the scripted runner through the run host
- **THEN** every message validates against the contract and the host derives the outcome the fixture states

#### Scenario: Provenance is recorded
- **WHEN** a fixture is read
- **THEN** it names the Claude Code version, the date, the command used and the scrubbing applied

#### Scenario: A context-limit fixture is captured with compaction off
- **WHEN** the capture tool captures `context-limit-refused` or `context-limit-blocked`
- **THEN** Claude Code is launched as the runner launches it, the stand-in API receives no compaction request, and
  the tool refuses to write the fixture if it does
