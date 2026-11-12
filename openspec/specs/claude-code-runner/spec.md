# claude-code-runner Specification

## Purpose

Capability: `cap:actor-runners`

Runs an actor through Claude Code. The runner speaks troupe's runner contract and maps Claude Code's stream-json onto
run events, so `troupe perform` can use the engine troupe was designed around.

## Requirements

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
USD 5, a named setting in one place in the runner. The runner SHALL always pass a permission mode that denies every
tool call no rule allows: `plan` when the options set it, and otherwise `dontAsk`, so the runner never grants more
than config asks for.

#### Scenario: No budget in the options
- **WHEN** a run starts without `maxBudgetUsd`
- **THEN** Claude Code is given `--max-budget-usd 5`

#### Scenario: A budget in the options
- **WHEN** a run starts with `maxBudgetUsd` 0.1
- **THEN** Claude Code is given `--max-budget-usd 0.1`

#### Scenario: No permission mode in the options
- **WHEN** a run starts without `permissionMode`
- **THEN** Claude Code is given `--permission-mode dontAsk`

### Requirement: Options reach Claude Code without free text on its command line
`model`, `maxBudgetUsd` and the permission mode SHALL be passed as Claude Code's flags of those names. `allowedTools`
and `disallowedTools`, and the rules translated from the effects, SHALL be passed as permission rules in a settings
file outside the workspace, so no value from config is parsed by a shell on any platform.

#### Scenario: Tool rules with spaces and parentheses
- **WHEN** `allowedTools` is `["Bash(git status)", "Read"]`
- **THEN** Claude Code is given `--settings` naming a file whose `permissions.allow` holds those two rules, and no
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
- **THEN** the event is `result` with status `error`, message `error_max_budget_usd` and `reason` `budget`

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

### Requirement: Write effects become edit rules
The runner SHALL translate each `write` pattern into an allow rule for Claude Code's file-editing tools, `Edit(//…)`,
rooted at the workspace's absolute path in Claude Code's form (`//c/…` for a Windows drive). It SHALL deny editing
under the workspace's `.git` and `.troupe`. Its `init` event SHALL report `effects` as `translated`.

#### Scenario: A write pattern
- **WHEN** the workspace is `/w/t` and `effects.write` is `["out/**"]`
- **THEN** the settings file's `permissions.allow` holds `Edit(//w/t/out/**)`, and `permissions.deny` holds
  `Edit(//w/t/.git/**)` and `Edit(//w/t/.troupe/**)`

#### Scenario: A read-only actor
- **WHEN** the actor declares no effects
- **THEN** the settings file allows no `Edit` rule other than the scratch directory's

#### Scenario: A write pattern on Windows
- **WHEN** the workspace is `C:\w\t` and `effects.write` is `["src/*.py"]`
- **THEN** `permissions.allow` holds `Edit(//c/w/t/src/*.py)`

### Requirement: The scratch directory is Claude Code's to use
The runner SHALL let Claude Code read and edit anything in the run's scratch directory, add it as a working
directory, and point Claude Code's temporary-directory variables at it. The runner's own private files SHALL stay
outside the scratch directory, where Claude Code can't edit them.

#### Scenario: Scratch in the settings file
- **WHEN** a run starts with scratch `/s/run`
- **THEN** Claude Code is given `--add-dir /s/run`, its `permissions.allow` holds `Edit(//s/run/**)`, and `TMPDIR` in
  its environment is `/s/run`
- **AND** the settings file isn't under `/s/run`

### Requirement: Delete and move effects are troupe's own tools
When the actor declares `delete` or `move`, the runner SHALL offer Claude Code troupe's `Delete` and `Move` tools,
carried out by the SDK and checked against the declaration on each call, through an MCP server of its own named only
by `--mcp-config`, and allow them by rule. Their calls and results SHALL be reported as the runner reports other tool
calls. With neither declared, the runner SHALL offer no MCP server.

#### Scenario: A declared delete
- **WHEN** the actor declares `delete` for `drafts/**` and Claude Code calls troupe's `Delete` on `drafts/a.md`
- **THEN** the file is removed, and a `tool_call` and `tool_result` for it are reported

#### Scenario: A refused move
- **WHEN** the actor declares `move` for `drafts/**` and Claude Code calls troupe's `Move` from `drafts/a.md` to
  `docs/a.md`
- **THEN** the result Claude Code gets is an error naming the `move` effect, and nothing moves

#### Scenario: Nothing to delete or move
- **WHEN** the actor declares only `write`
- **THEN** Claude Code is given no `--mcp-config`

### Requirement: Options can't widen the effects
`run/start` SHALL be refused with `claude-code.widens-effects`, naming the option and the effect to declare
instead, when `permissionMode` is `acceptEdits`, `auto`, `bypassPermissions` or `manual`, or when `allowedTools`
holds a rule for `Edit`, `Write`, `NotebookEdit`, `MultiEdit` or troupe's own tools. `disallowedTools` MAY name any
tool, since a deny only narrows.

#### Scenario: An actor that accepts edits
- **WHEN** the options set `permissionMode` to `acceptEdits`
- **THEN** `run/start` is refused with `claude-code.widens-effects`, whose fix says to declare `effects.write` and
  unset `permissionMode`

#### Scenario: An allowed edit rule
- **WHEN** `allowedTools` holds `Edit(src/**)`
- **THEN** `run/start` is refused with `claude-code.widens-effects`, naming `allowedTools` and `Edit(src/**)`

#### Scenario: A denied edit rule
- **WHEN** `disallowedTools` holds `Edit(docs/**)`
- **THEN** the run starts, with `Edit(docs/**)` in `permissions.deny`

### Requirement: What the translation can't cover is said, not hidden
Before the result, the runner SHALL send a `log` warning naming what can change files outside the translated rules:
each allowed `Bash` or `PowerShell` rule, and any loaded setting source, whose rules Claude Code merges with the
runner's. It SHALL turn off Claude Code's automatic allowing of sandboxed shell commands.

#### Scenario: An allowed shell command
- **WHEN** `allowedTools` holds `Bash(uv run pytest *)`
- **THEN** the run's events include a `log` warning that `Bash(uv run pytest *)` can change files the effects don't
  declare, and that troupe's audit checks them after the run

#### Scenario: Project settings loaded
- **WHEN** `settingSources` holds `project`
- **THEN** the run's events include a `log` warning that the project's settings may allow more than the effects
  declare

### Requirement: A pattern Claude Code would read differently is refused
`run/start` SHALL be refused with `claude-code.untranslatable-pattern`, naming the pattern or path and the character,
when a `write` pattern holds `[`, `]`, `(`, `)`, a backslash or a leading `!`, or the workspace's or scratch
directory's path holds one of those or `*` or `?`: characters Claude Code's rule syntax reads differently, or as
the rule's end. `delete` and `move` patterns SHALL be kept whatever they hold, since troupe's own tools read them.

#### Scenario: A bracket in a pattern
- **WHEN** `effects.write` holds `app/[id]/page.tsx`
- **THEN** `run/start` is refused with `claude-code.untranslatable-pattern`, naming the pattern and `[`

### Requirement: The runner's tests stop it as troupe would
A test that starts the Claude Code runner SHALL end it the way troupe ends a runner: the runner starts in a process
group (or the platform's equivalent) of its own, and the test's teardown kills that whole group, so the stand-in
`claude` the runner started ends with it, on Linux, macOS and Windows.

#### Scenario: A test ends while the stand-in hangs
- **WHEN** a test starts a run whose stand-in `claude` hangs, sends a second `run/start`, and ends without
  cancelling the run
- **THEN** after the test's teardown neither the runner nor the stand-in is running

### Requirement: A runner test that leaves its stand-in running fails
When a test of the runner process ends, its teardown SHALL kill the runner and then check that the stand-in `claude`
it started, as named by the pid the stand-in recorded, has ended within a named limit. A stand-in still running SHALL
fail the test, naming the stand-in's pid and the run's workspace. A record that names no pid SHALL fail the test,
naming the record, rather than read as no stand-in.

#### Scenario: A runner killed without its stand-in
- **WHEN** a test's teardown kills its runner in a way that leaves the stand-in running
- **THEN** the test fails at teardown, naming the stand-in's pid and the run's workspace

#### Scenario: A stand-in that ended with its runner
- **WHEN** a test's stand-in `claude` has ended by the time its runner has been killed
- **THEN** the test's teardown passes

#### Scenario: A record that names no pid
- **WHEN** a stand-in's record exists but holds no readable pid
- **THEN** the check fails, naming the record and what it holds

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

### Requirement: An assistant message's other model is a served_model event
When an `assistant` record's `message.model` isn't empty, isn't `<synthetic>` (Claude Code's mark on a message it made
itself) and isn't the model `system/init` named, the runner SHALL send `served_model` naming it, the first time that
model appears in the run, before the record's `turn` and tool calls. A subagent's messages count the same.

#### Scenario: A fallback model answers
- **WHEN** `system/init` names `claude-opus-5-5` and an assistant record's `message.model` is `claude-sonnet-5-5`
- **THEN** the runner sends `served_model` with `model` `claude-sonnet-5-5`, then that record's `turn` and tool calls

#### Scenario: A message Claude Code made itself
- **WHEN** an assistant record's `message.model` is `<synthetic>`
- **THEN** no `served_model` is sent for it

#### Scenario: Init's own model
- **WHEN** every assistant record's `message.model` is the model `system/init` named
- **THEN** the run has no `served_model`

### Requirement: The result's other models are served_model events before it
For each model named in the `result` record's `modelUsage` that isn't `<synthetic>`, isn't `system/init`'s model and
hasn't been reported, the runner SHALL send `served_model`, in the order `modelUsage` lists them, before the
permission-denial `log` warnings and the `result`.

#### Scenario: A model only the result names
- **WHEN** `system/init` names `claude-opus-5-5`, every assistant record is from it, and the result's `modelUsage` has
  `claude-opus-5-5` and `claude-haiku-5-5`
- **THEN** the runner sends `served_model` with `model` `claude-haiku-5-5`, then the `result`

#### Scenario: A model already reported
- **WHEN** an assistant record already led to `served_model` for `claude-sonnet-5-5`, and the result's `modelUsage`
  names it too
- **THEN** no second `served_model` is sent for it

### Requirement: Claude Code's context limit maps to context-length
An `is_error` result record under subtype `success` whose `terminal_reason` is `prompt_too_long` (the API refused the
request as too long) or
`blocking_limit` (Claude Code stopped before sending a request that would not fit) SHALL map to a `result` with status
`error` and `reason` `context-length`, whatever error code or retry came before it. A failed subtype still maps by its
subtype.

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

#### Scenario: A failed subtype that names the context limit
- **WHEN** a result record has subtype `error_during_execution`, `is_error` true and `terminal_reason`
  `prompt_too_long`
- **THEN** the `result` has `reason` `engine`

### Requirement: Claude Code compacts only when the run says compact
The runner SHALL set `autoCompactEnabled` in the settings file it gives Claude Code with `--settings`: `true` when the
run's `onContextFull` is `compact`, and `false` otherwise, whatever its options. When it's `compact`, the runner SHALL
leave `DISABLE_AUTO_COMPACT` out of Claude Code's environment, and when it was set, send a `log` event at level
`warning` naming it.

#### Scenario: A run told fail
- **WHEN** a run starts with `onContextFull` `fail` and no options
- **THEN** the settings file Claude Code is given with `--settings` holds `autoCompactEnabled` `false`

#### Scenario: A run told fail that loads project settings
- **WHEN** a run starts with `onContextFull` `fail` and `settingSources` `["project"]`
- **THEN** the settings file Claude Code is given with `--settings` still holds `autoCompactEnabled` `false`

#### Scenario: A run told compact
- **WHEN** a run starts with `onContextFull` `compact`
- **THEN** the settings file holds `autoCompactEnabled` `true`

#### Scenario: A person's variable that would turn it off
- **WHEN** a run told `compact` starts in an environment with `DISABLE_AUTO_COMPACT` `1`
- **THEN** Claude Code's environment has no `DISABLE_AUTO_COMPACT`
- **AND** the run sends a `log` event at level `warning`, after `init`, naming `DISABLE_AUTO_COMPACT` and saying the
  run's `onContextFull` overrides it

#### Scenario: A run told compact with no such variable
- **WHEN** a run told `compact` starts in an environment without `DISABLE_AUTO_COMPACT`
- **THEN** no `log` event names `DISABLE_AUTO_COMPACT`

### Requirement: Claude Code's compaction is a context event
A `system` record with subtype `compact_boundary` SHALL map to a `context` event with `kind` `compacted` and `by`
`engine`, carrying `tokensBefore` from its `compact_metadata.pre_tokens` and `tokensAfter` from `post_tokens`, each
when it is a whole number of zero or more.
`system` records with status `compacting` or a `compact_result` SHALL map to debug `log` events, not `context` events.

#### Scenario: A compaction that succeeds
- **WHEN** the `compaction-proactive` fixture plays
- **THEN** the runner sends one `context` event with `kind` `compacted`, `by` `engine`, and `tokensBefore` and
  `tokensAfter` from the boundary record, before the events of the turn that follows it, and the run ends `ok`

#### Scenario: A compaction after a refusal
- **WHEN** the `compaction-reactive` fixture plays: the API refuses a request as too long, and Claude Code compacts
- **THEN** the runner sends one `context` event with `kind` `compacted` and `by` `engine`, and the run ends `ok`

#### Scenario: A compaction that fails
- **WHEN** a run's records show status `compacting`, then a `compact_result` of `failed`, then a result record with
  `terminal_reason` `blocking_limit`
- **THEN** no `context` event is sent, and the run ends with `error` and `reason` `context-length`

#### Scenario: A compaction the run didn't ask for
- **WHEN** a run told `fail` receives a `compact_boundary` record
- **THEN** the runner still sends a `context` event for it

### Requirement: The capture tool records compaction fixtures only when Claude Code compacted
The capture tool SHALL capture compaction fixtures through the runner's own command with `onContextFull` `compact`,
against a stand-in API that answers Claude Code's compaction request with a summary. It SHALL refuse to write one
unless it saw a `compact_boundary` record.

#### Scenario: No compaction seen
- **WHEN** a compaction capture ends without a `compact_boundary` record
- **THEN** the tool writes no fixture, and says compaction wasn't seen
