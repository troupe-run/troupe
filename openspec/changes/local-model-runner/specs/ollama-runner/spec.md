# Spec Delta

## Purpose

Capability: `cap:actor-runners`

An actor runner for a model served by Ollama: it drives Ollama's own chat API with troupe's own tool loop, checking
each tool call against the actor's declared effects, and reports the run through the runner contract, with no
credential, no cost per run and no network beyond the endpoint.

## ADDED Requirements

### Requirement: The Ollama runner is a self-contained plugin
The Ollama runner SHALL be an out-of-process plugin with its own package and tests. It SHALL speak only the runner
contract, using the plugin SDK's types for it, and SHALL import nothing of troupe's but the SDK. It SHALL declare no
dependency other than the SDK, and SHALL start no process.

#### Scenario: The plugin's imports
- **WHEN** code under `plugins/runner-ollama/` imports `troupe.core`
- **THEN** the import contract check fails

#### Scenario: The plugin's dependencies
- **WHEN** `plugins/runner-ollama/pyproject.toml` is read
- **THEN** its only dependency is `troupe-plugin-sdk`

### Requirement: The runner identifies itself as ollama
The runner SHALL answer `initialize` with the name `ollama` and its package's version. Its `init` event SHALL name
the runner the same way, the engine `ollama` with the version Ollama reports and the model from the options, the
seven SDK tools, and `effects` `checked`.

#### Scenario: Init for a run
- **WHEN** a run starts with `model` `qwen3:4b` against an Ollama that reports version `0.12.6`
- **THEN** the `init` event's engine is `{"name": "ollama", "version": "0.12.6", "model": "qwen3:4b"}`, its tools are
  `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Delete` and `Move`, and its `effects` is `checked`

### Requirement: The runner's options are closed
`run/start` options SHALL be an object with `model` (required) and optionally `endpoint`, `maxTurns`, `contextLength`,
`temperature`, `seed` and `think`. An option the runner doesn't define SHALL be refused with
`ollama.unknown-option`, and a missing `model` or a value of the wrong shape with `ollama.invalid-options`, each
naming the option in `details.where`, and no run starts.

#### Scenario: An unknown option
- **WHEN** the options hold `troupeConformanceUnknownOption`
- **THEN** `run/start` is refused with `ollama.unknown-option`, whose `details.where` names the option

#### Scenario: No model
- **WHEN** the options are `{}`
- **THEN** `run/start` is refused with `ollama.invalid-options`, naming `model`

#### Scenario: A malformed value
- **WHEN** `maxTurns` is `0` or `think` is `"maximum"`
- **THEN** `run/start` is refused with `ollama.invalid-options`, naming the option, and its fix names what is valid

### Requirement: The endpoint is an option with a named default
The runner SHALL send every request to `endpoint` when the options set it, and otherwise to `http://127.0.0.1:11434`,
a named setting in one place in the runner. An endpoint SHALL be an `http` or `https` URL with a host and an optional
port, and SHALL be refused with `ollama.invalid-options` when it holds a user name or password, a path other than
`/`, a query, a fragment, a port above 65535, or a host name part that's empty or over 63 characters.

#### Scenario: No endpoint in the options
- **WHEN** a run starts without `endpoint`
- **THEN** the runner's requests go to `http://127.0.0.1:11434`

#### Scenario: An endpoint on another host
- **WHEN** a run starts with `endpoint` `http://gpu-box.local:11434`
- **THEN** the runner's requests go to that host

#### Scenario: A port or host name no connection could use
- **WHEN** `endpoint` is `http://127.0.0.1:99999` or `http://a..b:11434`
- **THEN** `run/start` is refused with `ollama.invalid-options`, naming `endpoint`, and the runner keeps serving

#### Scenario: Credentials in the endpoint
- **WHEN** `endpoint` is `http://user:secret@127.0.0.1:11434`
- **THEN** `run/start` is refused with `ollama.invalid-options`, naming `endpoint`, and its message doesn't hold
  `secret`

### Requirement: The runner checks the engine before it acknowledges the run
Before answering `run/start`, the runner SHALL ask Ollama for its version and for the model, within a named time
limit. It SHALL refuse the run with `ollama.unreachable` when Ollama doesn't answer, `runner.requirement-unmet` when
Ollama's version doesn't meet its requirements, `ollama.model-not-found` when the model isn't there, and
`ollama.model-without-tools` when it can't call tools.

#### Scenario: A run start the runner can't carry out
- **WHEN** a `run/start`'s scratch directory doesn't exist
- **THEN** it is refused with `runner.invalid-params`, and no run is acknowledged

#### Scenario: Ollama isn't running
- **WHEN** nothing listens at the endpoint
- **THEN** `run/start` is refused with `ollama.unreachable`, naming the endpoint, and the fix says to start Ollama or
  set `endpoint`

#### Scenario: An Ollama too old for the runner
- **WHEN** Ollama reports version `0.12.5`
- **THEN** `run/start` is refused with `runner.requirement-unmet`, naming `ollama`, the version wanted and `0.12.5`,
  and the fix says to upgrade Ollama

#### Scenario: A version the runner can't read
- **WHEN** Ollama reports a version that isn't numbers separated by dots, with an optional suffix
- **THEN** `run/start` is refused with `runner.requirement-unmet`, naming what Ollama reported

#### Scenario: A model that isn't pulled
- **WHEN** Ollama answers that `qwen3:4b` isn't there
- **THEN** `run/start` is refused with `ollama.model-not-found`, and the fix names `ollama pull qwen3:4b`

#### Scenario: A model that can't call tools
- **WHEN** Ollama's description of the model doesn't list the `tools` capability
- **THEN** `run/start` is refused with `ollama.model-without-tools`, naming the model

### Requirement: The runner publishes its platform requirements as data
The runner SHALL publish what it requires of the platform as data in its package, beside its schemas, each with the
thing required, the least version and why, and SHALL check Ollama against that data, not against a version written in
its code. The first requirement SHALL be Ollama 0.12.6 or later.

#### Scenario: The published requirement
- **WHEN** the runner's published requirements are read
- **THEN** they hold `ollama` at least `0.12.6`, with a reason naming the `truncate` and `shift` fields

#### Scenario: The check reads the data
- **WHEN** the published requirement is changed to `0.50.0` and Ollama reports `0.40.14`
- **THEN** `run/start` is refused with `runner.requirement-unmet`, naming `0.50.0`

### Requirement: The character and the direction start the conversation
The first request SHALL hold the character as a `system` message, when the actor has one, then the direction as a
`user` message, each unchanged. An actor with no character SHALL have no `system` message.

#### Scenario: An actor with a character
- **WHEN** a run starts with a character and a direction
- **THEN** the first request's messages are a `system` message holding the character and a `user` message holding
  the direction, in that order

#### Scenario: An actor with no character
- **WHEN** a run starts with no character
- **THEN** the first request's only message is the `user` message holding the direction

### Requirement: Every request offers the SDK's tools
Every request SHALL be a streamed `/api/chat` request for the model, offering the SDK's tool definitions for the
run's scratch directory as Ollama function tools, with the run's context window as `options.num_ctx`, the options'
`temperature`, `seed` and `think` passed as Ollama's own fields when they're set, and nothing else from config.

#### Scenario: The tools offered
- **WHEN** a run makes its first request
- **THEN** the request's `tools` holds one function per SDK tool, with the SDK's name, description and input schema,
  and `Write`'s description names the scratch directory

#### Scenario: A context length
- **WHEN** a run starts with `contextLength` 32768
- **THEN** each request's `options.num_ctx` is 32768

### Requirement: The runner always sets the context window
The run's context window SHALL be `contextLength` when the options set it, and otherwise a named default in the
runner, lowered to the model's own maximum when Ollama reports one. A `contextLength` above the model's maximum SHALL
be refused before the run is acknowledged, with `ollama.invalid-options` naming `contextLength` and the maximum.

#### Scenario: No context length in the options
- **WHEN** a run starts without `contextLength`, for a model whose maximum is above the default
- **THEN** each request's `options.num_ctx` is the runner's default, never left to Ollama

#### Scenario: A model with a smaller maximum
- **WHEN** a run starts without `contextLength`, for a model whose maximum is below the default
- **THEN** each request's `options.num_ctx` is the model's maximum

#### Scenario: A context length the model can't hold
- **WHEN** `contextLength` is above the maximum Ollama reports for the model
- **THEN** `run/start` is refused with `ollama.invalid-options`, naming `contextLength` and the maximum

### Requirement: One tool result fits the context window
Each tool result the runner sends the model SHALL be at most a named share of the run's context window, counted in
bytes at a named estimate of bytes per token. The runner SHALL lower the SDK's tool limits to fit that budget, and SHALL
cut a result still over it, adding a note that says it was cut to fit the window and how to narrow the call.

#### Scenario: A large file read with the default window
- **WHEN** a run with the default window reads a 200 KB text file
- **THEN** the `tool` message holds the file's first lines up to the budget, saying where it stopped and that
  `offset` reads on, and the run goes on

#### Scenario: A budget that follows the window
- **WHEN** one run sets `contextLength` 8192 and another 32768, and each reads the same large file
- **THEN** the second run's `tool` message holds more of the file than the first's, and each is within its budget

#### Scenario: A search with very long lines
- **WHEN** a `Grep` matches lines whose text together is over the budget
- **THEN** the `tool` message is cut to the budget and ends with a note saying it was cut to fit the context window,
  and to narrow the search with `path` or `glob`

### Requirement: A run never carries on past its context window
Every request SHALL ask Ollama to refuse a conversation longer than the window rather than cut it, and never to drop
its start to make room (`truncate` and `shift` both `false`). When Ollama refuses a request, the run SHALL end with an
`error` result holding Ollama's message and naming the window and `contextLength`.

#### Scenario: Every request asks Ollama not to cut
- **WHEN** a run makes a request
- **THEN** the request's `truncate` and `shift` are both `false`

#### Scenario: A conversation that outgrows the window
- **WHEN** Ollama answers a run's second request with status 400 and a message saying the request exceeds the
  context size
- **THEN** no third request is made, and the `result` has status `error`, holding Ollama's message and naming the
  window and `contextLength`

#### Scenario: A cut answer
- **WHEN** an answer ends with `done_reason` `length`
- **THEN** the runner sends a `log` warning saying the answer hit its output limit, and the run goes on

### Requirement: Each tool call is carried out by the SDK and its result sent back
Each tool call in an answer SHALL be carried out with the SDK's tools for the run's declaration, in the order the
answer gives them, and its output, error or not, sent back in the next request as a `tool` message naming the tool.
A call Ollama gives no id SHALL get one the runner makes, unique in the run.

#### Scenario: A Write the effects allow
- **WHEN** the actor declares `write` for `out/**` and the model calls `Write` on `out/a.txt`
- **THEN** `out/a.txt` is written, and the next request ends with a `tool` message for `Write` holding the SDK's
  output

#### Scenario: A call the effects refuse
- **WHEN** the actor declares no effects and the model calls `Delete` on `README.md`
- **THEN** `README.md` still exists, and the next request ends with a `tool` message for `Delete` holding the SDK's
  refusal, naming the `delete` effect

#### Scenario: Two calls in one answer
- **WHEN** one answer holds a `Read` call and then a `Grep` call
- **THEN** both are carried out in that order, each with its own call id, and the next request ends with their two
  `tool` messages in that order

### Requirement: The loop ends when the model stops calling tools
The runner SHALL keep making requests while answers hold tool calls. An answer with no tool call SHALL end the run
with an `ok` result whose message is the answer's text. Reaching `maxTurns` requests, by default a named setting of
50, SHALL end it with an `error` result saying the limit was reached.

#### Scenario: A final answer
- **WHEN** the model's answer holds text and no tool call
- **THEN** the runner sends an `ok` `result` whose message is that text, and makes no further request

#### Scenario: The turn limit
- **WHEN** `maxTurns` is 2 and both answers hold tool calls
- **THEN** after carrying out the second answer's calls the runner sends an `error` `result` naming the limit of 2,
  and makes no third request

### Requirement: Answers map to turns and tool calls
Each answer's text SHALL be one `turn` event with role `assistant`, sent when the answer ends and only when the text
isn't empty, followed by a `tool_call` and `tool_result` pair for each of its calls. The model's thinking SHALL appear
only in the transcript.

#### Scenario: An answer with text and a call
- **WHEN** an answer streams the text `Reading it.` in three parts, and one `Read` call
- **THEN** the runner sends one `turn` holding `Reading it.`, then that call's `tool_call` and `tool_result`

#### Scenario: Thinking
- **WHEN** an answer streams thinking and no text
- **THEN** no `turn` event is sent for it, and its thinking is in the transcript

### Requirement: The result carries the run's counts
The `result` SHALL carry the number of requests as `turns`, the run's duration, and as `usage` the sum over every
request of Ollama's prompt token count as `inputTokens` and its generated token count as `outputTokens`, leaving out
a counter no request reported. It SHALL carry no cost.

#### Scenario: Two requests
- **WHEN** a run's two requests report prompt counts 120 and 300, and generated counts 40 and 25
- **THEN** its `result` has `turns` 2 and `usage` `{"inputTokens": 420, "outputTokens": 65}`, and no `costUsd`

### Requirement: Ollama's errors end the run as error results
An error Ollama reports, as an HTTP error status or as an `error` record in a stream, that isn't retried SHALL end the
run with an `error` result holding Ollama's message. The runner SHALL NOT invent an `ok` result.

#### Scenario: A model that fails to load
- **WHEN** Ollama answers a request with status 500 and `{"error": "model failed to load"}`, and the retries are
  spent
- **THEN** the runner's `result` has status `error` and its message holds `model failed to load`

#### Scenario: An error part-way through a stream
- **WHEN** a stream sends text and then a record holding only `error`
- **THEN** the runner's `result` has status `error` and its message holds that error

#### Scenario: A request Ollama refuses
- **WHEN** Ollama answers a request with status 400
- **THEN** the run ends with an `error` result at once, with no retry

### Requirement: Connection failures and server errors are retried and reported
A request that can't connect, whose connection drops, that gets status 500, 502, 503 or 504, or whose stream goes
silent past a named limit SHALL be made again, up to a named number of attempts, after a named delay. Each retry SHALL
be a `retry` event, with reason `network` for a connection that failed or went silent and `server` for an error
status.

#### Scenario: A dropped connection
- **WHEN** the connection closes before the stream's final record, and the next attempt succeeds
- **THEN** the runner sends a `retry` event with reason `network` and attempt 1, and the run goes on

#### Scenario: A busy server
- **WHEN** Ollama answers status 503 twice and then streams an answer
- **THEN** the runner sends two `retry` events with reason `server` and attempts 1 and 2, then the answer's events

#### Scenario: Retries spent
- **WHEN** every attempt gets status 503
- **THEN** the runner sends one `retry` event per retry, then an `error` result naming the status

### Requirement: Every exchange with Ollama is a transcript record
The runner SHALL send as transcript records, before any event they lead to: the first request's body, then before each
later request each message it added to the conversation, each verbatim as sent, and every line of every streamed
answer and every error body, verbatim. It SHALL NOT send a request's re-sent history again.

#### Scenario: A run with one tool call
- **WHEN** a run's first answer calls `Read` once and its second answer ends the run
- **THEN** its transcript is the first request's body, the first answer's lines, the assistant message and the `tool`
  message the runner added, and the second answer's lines, in that order

#### Scenario: Re-sent history
- **WHEN** a run makes three requests
- **THEN** the system and user messages appear in the transcript once, in the first request's body

### Requirement: Summaries fit below the event limit
Every event's text SHALL be cut on a character boundary so the event fits `limits.eventMaxBytes`, saying how many bytes
were left out, and a `tool_result`'s `outputBytes` SHALL be the full output's size.

#### Scenario: A long final answer
- **WHEN** the final answer's text is 200 KB and `eventMaxBytes` is 65536
- **THEN** the `result` event's encoded size is at most 65536 bytes, and its message ends saying how much was left out

### Requirement: Cancel and end of input stop the run at once
On `run/cancel`, end of input, or `shutdown`, the runner SHALL close any request in flight, carry out no further tool
call, send no further event, and exit within a named grace well below troupe's own.

#### Scenario: Cancel while an answer streams
- **WHEN** troupe sends `run/cancel` while the fake endpoint is streaming an answer slowly
- **THEN** the runner acknowledges it, the fake endpoint sees its connection closed, no event follows the
  acknowledgement, and the runner exits

#### Scenario: End of input during a request
- **WHEN** the runner's standard input closes while a request waits for its first line
- **THEN** the runner closes the request and exits

### Requirement: The runner publishes its schemas
The runner SHALL publish `options.schema.json` and `errors.schema.json` in its package, passing the protocol's
strictness check, and its options parser SHALL accept and refuse exactly the options its published schema does.

#### Scenario: Parser and schema agree
- **WHEN** generated option objects are given to the runner's parser and to its published options schema
- **THEN** each object is accepted by both or refused by both

### Requirement: The runner conforms to the contract
The Ollama runner SHALL pass troupe's conformance suite against a fake Ollama endpoint.

#### Scenario: The conformance suite
- **WHEN** the conformance suite runs against the Ollama runner, with options naming a fake endpoint that serves a
  short successful run
- **THEN** every check passes

### Requirement: Fixtures pair real Ollama output with protocol events
The plugin SHALL hold fixtures captured from a real Ollama by a capture tool that needs no credential, each with its
provenance (Ollama's version, the model and the date), the exchange it recorded, and the run events the runner maps it
to. The fake endpoint SHALL serve them, and a test SHALL check that replaying each gives exactly its events.

#### Scenario: A fixture replayed
- **WHEN** a fixture's recorded answers are served by the fake endpoint to the runner
- **THEN** the runner sends exactly the fixture's events and transcript records

### Requirement: A live test runs a real model only when asked
A test against a real Ollama SHALL run only when `TROUPE_LIVE_OLLAMA=1` is set, and SHALL otherwise be reported
skipped, naming the variable. CI SHALL NOT set it.

#### Scenario: Without the variable
- **WHEN** the tests run without `TROUPE_LIVE_OLLAMA`
- **THEN** the live test is skipped with a reason naming `TROUPE_LIVE_OLLAMA`
