# Spec Delta

## Purpose

Runs an actor through Claude Code. The runner speaks troupe's runner contract and maps Claude Code's stream-json onto
run events, so `troupe perform` can use the engine troupe was designed around.

## ADDED Requirements

### Requirement: The Claude Code runner is a self-contained plugin
The Claude Code runner SHALL be an out-of-process plugin with its own package definition, tests and fixtures. It
SHALL use only the standard library, speak only the runner contract, and SHALL NOT import troupe. A check that fails
the build SHALL enforce the import rule.

#### Scenario: The plugin imports troupe
- **WHEN** code in the Claude Code runner's package imports `troupe`
- **THEN** the import contract check fails

### Requirement: The runner identifies itself as claude-code
The runner SHALL answer `initialize` with the runner name `claude-code` and its package version, and SHALL support
protocol version 0, refusing a handshake that offers none of its versions as the contract says.

#### Scenario: Handshake
- **WHEN** troupe offers protocol version 0
- **THEN** the runner answers version 0, name `claude-code`, its version and no capabilities

### Requirement: The runner starts Claude Code in print mode with stream-json output
On `run/start` the runner SHALL start `claude` found on the `PATH` it was given, in print mode with stream-json
output, verbose, without session persistence, with the workspace as its working directory. No option SHALL name the
program to run.

#### Scenario: The command line
- **WHEN** a run starts with no options
- **THEN** `claude` runs in the workspace with `-p`, `--output-format stream-json`, `--verbose` and
  `--no-session-persistence`

#### Scenario: Claude Code isn't installed
- **WHEN** no `claude` is on the runner's `PATH`
- **THEN** `run/start` is refused with `claude-code.not-found`, naming the `PATH` searched and the fix (install Claude
  Code), and no run starts

### Requirement: The direction reaches Claude Code on standard input
The runner SHALL write the direction to Claude Code's standard input as UTF-8 and then close it. The direction
SHALL NOT appear on Claude Code's command line.

#### Scenario: A direction with newlines and quotes
- **WHEN** the direction is `say "hi"` followed by a newline and `then stop`
- **THEN** Claude Code reads exactly those bytes on its standard input, and no argument of its command line contains
  them

### Requirement: The character is appended to the system prompt
When `run/start` carries a character, the runner SHALL give it to Claude Code as an appended system prompt, through a
file outside the workspace that the runner removes when the run ends. With no character, no system prompt flag SHALL
be passed.

#### Scenario: A character
- **WHEN** `run/start` carries a character
- **THEN** Claude Code is given `--append-system-prompt-file` naming a file outside the workspace that holds the
  character's UTF-8, and the file no longer exists after the runner exits

#### Scenario: No character
- **WHEN** `run/start` has no character
- **THEN** Claude Code is given no system prompt flag

### Requirement: The person's Claude Code settings are left out by default
By default the runner SHALL start Claude Code with no setting sources and with only the MCP servers it is given (none),
so the actor runs no settings, hooks or MCP servers from the person or the workspace. The `settingSources` option SHALL
name the sources to load instead.

#### Scenario: Default isolation
- **WHEN** a run starts without `settingSources`
- **THEN** Claude Code is given `--setting-sources ""` and `--strict-mcp-config`

#### Scenario: Opting in to project settings
- **WHEN** a run starts with `settingSources` `["project"]`
- **THEN** Claude Code is given `--setting-sources project`

### Requirement: The runner's options are closed
`run/start` options SHALL be an object with only `model`, `maxBudgetUsd`, `permissionMode`, `allowedTools`,
`disallowedTools` and `settingSources`, each optional. An option the runner doesn't define, or a value of the wrong
shape, SHALL be refused with an error naming it, and no run starts.

#### Scenario: An unknown option
- **WHEN** the options hold `troupeConformanceUnknownOption`
- **THEN** `run/start` is refused with `claude-code.unknown-option`, whose `details.where` names the option

#### Scenario: A malformed value
- **WHEN** `maxBudgetUsd` is `-1` or `permissionMode` is `yolo`
- **THEN** `run/start` is refused with `claude-code.invalid-options`, whose `details.where` names the option and whose
  fix names what is valid

### Requirement: Every run has a budget
The runner SHALL always pass Claude Code a budget: `maxBudgetUsd` when the options set it, and otherwise a default of
USD 5, a named setting in one place in the runner. Permission mode SHALL be passed only when `permissionMode` is set,
so the runner never grants more than config asks for.

#### Scenario: No budget in the options
- **WHEN** a run starts without `maxBudgetUsd`
- **THEN** Claude Code is given `--max-budget-usd 5`

#### Scenario: A budget in the options
- **WHEN** a run starts with `maxBudgetUsd` 0.1
- **THEN** Claude Code is given `--max-budget-usd 0.1`

#### Scenario: No permission mode in the options
- **WHEN** a run starts without `permissionMode`
- **THEN** Claude Code is given no `--permission-mode`

### Requirement: Options reach Claude Code without free text on its command line
`model`, `maxBudgetUsd` and `permissionMode` SHALL be passed as Claude Code's flags of those names. `allowedTools` and
`disallowedTools` SHALL be passed as permission rules in a settings file outside the workspace, so no value from
config is parsed by a shell on any platform.

#### Scenario: Tool rules with spaces and parentheses
- **WHEN** `allowedTools` is `["Bash(git status)", "Read"]`
- **THEN** Claude Code is given `--settings` naming a file whose `permissions.allow` is those two rules, and no
  argument of its command line contains them

### Requirement: Every native line is a transcript record
The runner SHALL send each line Claude Code writes to standard output as one `run/transcript` record, unchanged and
in order, before any event that line maps to. A line that isn't valid UTF-8 SHALL be sent with `base64` encoding.

#### Scenario: Fixture lines are kept byte for byte
- **WHEN** a fixture's native lines are played through the runner
- **THEN** the run's transcript is those lines, each followed by `\n`, byte for byte

### Requirement: System init maps to the init event
A `system` record with subtype `init` SHALL map to the `init` event: runner `claude-code` and its version, the
record's `tools`, and engine name `claude-code` with the record's `claude_code_version` and `model`.

#### Scenario: Init from a fixture
- **WHEN** the `success-with-tools` fixture's init line is mapped
- **THEN** the event is `init` with engine version `2.1.296`, model `claude-haiku-5-5` and the record's 22 tools

### Requirement: The runner sends init before any other event
`init` SHALL be the first event. A `log` about a record before the init record SHALL be held and sent after `init`.
If any other event comes before the init record, or Claude Code ends without one, the runner SHALL first send an
`init` with no `engine` and no tools.

#### Scenario: A record before the init record
- **WHEN** Claude Code writes a `system` record of subtype `ui_invalidate`, then its init record
- **THEN** the first event is the `init` mapped from the init record, followed by the `debug` log noting
  `ui_invalidate`

#### Scenario: Claude Code exits before its init
- **WHEN** Claude Code writes nothing to standard output and exits 1
- **THEN** the runner sends `init` with no `engine`, a `log` error naming the exit code, and no `result`

### Requirement: Assistant messages map to turns and tool calls
An `assistant` record SHALL map to a `turn` with role `assistant` for its text blocks joined, when it has any text,
then one `tool_call` per `tool_use` block with its id, its tool name and its input as compact JSON. An API failure,
an `assistant` record with `error` set, maps the same way.

#### Scenario: A tool call
- **WHEN** an assistant record holds one `tool_use` block for `Write` with id `toolu_1`
- **THEN** the event is `tool_call` with `callId` `toolu_1`, `tool` `Write` and `inputSummary` the input as compact
  JSON

#### Scenario: An API failure
- **WHEN** an assistant record has `error` `authentication_failed` and the text `Invalid API key`
- **THEN** the event is a `turn` with role `assistant` and text `Invalid API key`

### Requirement: Tool results map to tool_result events
A `user` record's `tool_result` blocks SHALL each map to a `tool_result` with the block's `tool_use_id`, `isError`
from its `is_error` (false when absent), its text as `outputSummary`, and its text's UTF-8 length as `outputBytes`.
A block whose id matches no earlier `tool_call` SHALL map to a `log` warning instead.

#### Scenario: A tool result
- **WHEN** a user record holds a `tool_result` for `toolu_1` with content `1\thi`
- **THEN** the event is `tool_result` with `callId` `toolu_1`, `isError` false, `outputSummary` `1\thi` and
  `outputBytes` 4

#### Scenario: A result for an unknown call
- **WHEN** a `tool_result` names an id no `tool_call` had
- **THEN** the runner sends a `log` warning naming the id, and no `tool_result`

### Requirement: API retries map to retry events
A `system` record with subtype `api_retry` SHALL map to `retry` with its attempt, `max_retries` as `maxAttempts`, and
`retry_delay_ms` as `delayMs`. Its reason SHALL be `authentication` for error `authentication_failed`, `rate-limit`
for status 429, `server` for 5xx, `network` for no status, and `other` otherwise.

#### Scenario: An authentication retry
- **WHEN** an `api_retry` record has error `authentication_failed` and status 401
- **THEN** the event is `retry` with reason `authentication` and message `authentication_failed (HTTP 401)`

#### Scenario: A refused connection
- **WHEN** an `api_retry` record has error `unknown` and status null
- **THEN** the event is `retry` with reason `network` and message `unknown (no HTTP response)`

### Requirement: Rate limit records are reported only when not allowed
A `rate_limit_event` record SHALL map to no event while its status is `allowed`, and otherwise to a `log` warning
naming the status and the limit's type.

#### Scenario: Allowed
- **WHEN** a `rate_limit_event` has status `allowed`
- **THEN** no event is sent, and the line is still in the transcript

#### Scenario: Rejected
- **WHEN** a `rate_limit_event` has status `rejected` and type `five_hour`
- **THEN** the event is a `log` warning naming `rejected` and `five_hour`

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
- **THEN** the event is `result` with status `error` and message `error_max_budget_usd`

### Requirement: Permission denials are reported before the result
When a `result` record lists permission denials, the runner SHALL send a `log` warning naming each denied tool before
the `result` event.

#### Scenario: A denied write
- **WHEN** a result record's `permission_denials` names `Write` once
- **THEN** a `log` warning naming `Write` comes immediately before the `result`

### Requirement: Records the mapping doesn't name are kept and noted
A record type, or system subtype, the mapping doesn't name SHALL map to no event except a `debug` log the first time
that type appears in the run. A line that isn't a JSON object SHALL map to a `warning` log. Neither SHALL end the run.

#### Scenario: A new record type
- **WHEN** Claude Code writes two records of a type `widget` the mapping doesn't know
- **THEN** the runner sends one `debug` log naming `widget`, and both lines are in the transcript

#### Scenario: A line that isn't JSON
- **WHEN** Claude Code writes the line `Update available`
- **THEN** the runner sends a `log` warning saying a line wasn't JSON, and the line is in the transcript

### Requirement: The runner never invents a result
The runner SHALL send a `result` only for a `result` record Claude Code wrote. When Claude Code ends without one, the
runner SHALL send no `result`. A `result` record it can't read SHALL map to a `log` error and no `result`.

#### Scenario: Terminated without a result
- **WHEN** the `terminated-no-result` fixture plays and Claude Code exits 143
- **THEN** the runner sends no `result`, and the host derives the outcome the fixture states

### Requirement: Summaries fit below the event limit
Each `turn` text, `inputSummary` and `outputSummary` SHALL be cut, on a UTF-8 boundary, so that the event serialises
within `limits.eventMaxBytes` and the runner's own summary limit. A cut summary SHALL end by saying how many bytes were
left out.

#### Scenario: A long tool output
- **WHEN** a tool result's text is 1 MiB and `eventMaxBytes` is 65536
- **THEN** the `tool_result` event serialises within 65536 bytes, its `outputBytes` is 1048576, and its summary ends
  by naming the bytes left out

### Requirement: Cancel stops Claude Code before the runner exits
On `run/cancel`, the runner SHALL answer, stop Claude Code and exit, sending no further events. It SHALL ask Claude
Code to stop (SIGTERM on POSIX, termination on Windows), kill it if it hasn't exited within its stop grace, and SHALL
NOT exit while it is running.

#### Scenario: Cancel during a run
- **WHEN** troupe cancels a run while Claude Code is working
- **THEN** the runner answers `{}`, Claude Code's process has ended before the runner exits, and the outcome is
  `cancelled`, on Linux, macOS and Windows

### Requirement: End of input stops Claude Code
When the runner's standard input closes, it SHALL stop Claude Code as cancel does and exit.

#### Scenario: troupe goes away
- **WHEN** the runner's standard input closes during a run
- **THEN** Claude Code's process ends, and then the runner exits

### Requirement: The runner's exit reports how Claude Code ended
After a `result`, the runner SHALL answer `shutdown` once Claude Code has exited, and exit 0 only if Claude Code
exited 0. Otherwise it SHALL exit non-zero. It SHALL write Claude Code's exit code, and Claude Code's own standard
error, to its standard error.

#### Scenario: Claude Code fails after an ok result
- **WHEN** Claude Code sends an `ok` result and then exits 1
- **THEN** the runner exits non-zero, and the outcome is `failed` with `run.unclean-exit`

### Requirement: The runner publishes its schemas
The runner SHALL publish `options.schema.json` and `errors.schema.json` in its package's `schemas/` directory,
installed with it, closed as the contract requires. The error codes SHALL be `claude-code.not-found`,
`claude-code.unknown-option`, `claude-code.invalid-options` and `claude-code.start-failed`, each with its `details`.

#### Scenario: Messages validate against the bound schemas
- **WHEN** a test binds the runner's schemas into the contract and validates every message either side sends
- **THEN** every message validates, and each option the tests refuse is refused by the options schema too

### Requirement: The runner conforms to the contract
The Claude Code runner SHALL pass troupe's runner conformance suite, run against a stand-in `claude` that replays a
fixture.

#### Scenario: Conformance
- **WHEN** the conformance suite runs against the Claude Code runner with the stand-in on its `PATH`
- **THEN** every check passes

### Requirement: Fixtures pair real Claude Code output with protocol events
The plugin SHALL include fixtures captured from real Claude Code runs. Each SHALL pair the native lines, unchanged
except for scrubbing, with the events they map to, and record its provenance. They SHALL cover the `success` subtype
with `is_error`, retries for authentication, network, server and rate limits, a run with no `result`, and a success
with tools.

#### Scenario: The mapping reproduces each fixture
- **WHEN** each fixture's native lines are mapped by the runner
- **THEN** the transcript records and events are exactly the fixture's, in order

#### Scenario: Fixtures replay through the contract
- **WHEN** each fixture is replayed by the scripted runner through the run host
- **THEN** every message validates against the contract and the host derives the outcome the fixture states

#### Scenario: Provenance is recorded
- **WHEN** a fixture is read
- **THEN** it names the Claude Code version, the date, the command used and the scrubbing applied

### Requirement: Fixtures hold no secrets
No committed fixture SHALL contain a credential, a token, a host user name, account usage or a host path outside the
run's workspace. A test SHALL check every fixture for the known patterns.

#### Scenario: A secret pattern in a fixture
- **WHEN** a fixture contains a string matching a credential pattern or the capturing host's home path
- **THEN** the fixture check fails and names the fixture and line

### Requirement: Fixtures are captured without a credential where possible
The capture tool SHALL capture every failure fixture against a local stand-in for the API, or an unreachable
address, with a deliberately invalid key, so nothing reaches Anthropic. Only the success fixture SHALL need a real
credential, and the owner captures it.

#### Scenario: A server error fixture
- **WHEN** the capture tool captures `server-retries`
- **THEN** Claude Code talks only to a local server that answers 529, and the provenance says no credential was used

### Requirement: A live test runs real Claude Code only when asked
An opt-in test SHALL run the runner against real Claude Code. It SHALL run only when `TROUPE_LIVE_CLAUDE_CODE` is `1`,
never in CI, with a pinned model and a budget cap. It SHALL use `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY` or the
person's existing login, and say which.

#### Scenario: Not asked
- **WHEN** the test suite runs without `TROUPE_LIVE_CLAUDE_CODE`
- **THEN** the live test is skipped, saying how to run it

#### Scenario: A live run
- **WHEN** the owner runs it with `TROUPE_LIVE_CLAUDE_CODE=1` and a credential
- **THEN** a run that writes and reads back a file, with only `Write` and `Read` allowed, ends `succeeded` within its
  budget, and the file holds what was asked
