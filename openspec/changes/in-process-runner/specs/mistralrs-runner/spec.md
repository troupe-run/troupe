# Spec Delta

## Purpose

Capability: `cap:actor-runners`

An actor runner for a model loaded inside its own process by mistral.rs: it drives the model with troupe's own tool
loop, checking each tool call against the actor's declared effects, and reports the run through the runner contract,
with no server, no credential, no cost per run and no network.

## ADDED Requirements

### Requirement: The mistralrs runner is a self-contained plugin
The runner SHALL be an out-of-process plugin with its own package and tests. It SHALL speak only the runner contract,
SHALL import nothing of troupe's but the plugin SDK, and SHALL depend only on the SDK and `mistralrs` at the version the
lock file pins. It SHALL start no process and make no network request.

#### Scenario: The plugin's imports
- **WHEN** code under `plugins/runner-mistralrs/` imports `troupe.core`
- **THEN** the import contract check fails

#### Scenario: The plugin's dependencies
- **WHEN** `plugins/runner-mistralrs/pyproject.toml` is read
- **THEN** its dependencies are `troupe-plugin-sdk` and `mistralrs` at one exact version

### Requirement: The runner's dependency installs everywhere troupe runs
`mistralrs` SHALL have a licence on troupe's list, and SHALL install from a published wheel on Linux, macOS and
Windows for every Python troupe supports. CI SHALL install `troupe-run[mistralrs]` on each of its legs.

#### Scenario: Every leg
- **WHEN** CI's install check runs on Linux, macOS and Windows, on each supported Python
- **THEN** `troupe-run[all]` installs, and an audition on the `mistralrs` runner is rehearsed

### Requirement: The runner identifies itself as mistralrs
The runner SHALL answer `initialize` with the name `mistralrs` and its package's version. Its `init` event SHALL name
the runner the same way, the engine `mistral.rs` with the installed `mistralrs` version and the run's model, the seven
SDK tools, and `effects` `checked`.

#### Scenario: Init for a run
- **WHEN** a run starts with the model `/models/qwen3-0.6b.gguf`, and `mistralrs` 0.9.5 is installed
- **THEN** the `init` event's engine is `{"name": "mistral.rs", "version": "0.9.5", "model":
  "/models/qwen3-0.6b.gguf"}`, its tools are `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Delete` and `Move`, and its
  `effects` is `checked`

### Requirement: The runner checks its engine's version against published data
The runner SHALL publish the `mistralrs` version it was built for as data beside its schemas, with why, and SHALL
refuse `run/start` with `runner.requirement-unmet` when the installed `mistralrs` is another version, naming both.

#### Scenario: Another version installed
- **WHEN** the published requirement is `0.9.5` and the installed `mistralrs` reports `0.9.4`
- **THEN** `run/start` is refused with `runner.requirement-unmet`, naming `mistralrs`, `0.9.5` and `0.9.4`

### Requirement: The runner's options are closed
`run/start` options SHALL be an object with optionally `maxTurns`, `contextLength`, `temperature`, `seed` and `think`.
An option the runner doesn't define SHALL be refused with `mistralrs.unknown-option`, and a value of the wrong shape
with `mistralrs.invalid-options`, each naming the option in `details.where`, and no run starts.

#### Scenario: An unknown option
- **WHEN** the options hold `troupeConformanceUnknownOption`
- **THEN** `run/start` is refused with `mistralrs.unknown-option`, whose `details.where` names the option

#### Scenario: A model in the options
- **WHEN** the options hold `model`
- **THEN** `run/start` is refused with `mistralrs.unknown-option`, naming `model`

#### Scenario: A malformed value
- **WHEN** `maxTurns` is `0` or `contextLength` is `"large"`
- **THEN** `run/start` is refused with `mistralrs.invalid-options`, naming the option, and its fix names what is
  valid

### Requirement: The model comes from the run's in-process runtime
The runner SHALL take its model from the run's runtime and nowhere else. A `run/start` with no runtime SHALL be refused
with `mistralrs.no-runtime`, and one whose runtime has an endpoint or a credential with `mistralrs.invalid-runtime`,
naming the field, each before any model is loaded.

#### Scenario: A run without a runtime
- **WHEN** a `run/start` carries no runtime
- **THEN** it is refused with `mistralrs.no-runtime`, whose fix says to name the runtime `mistralrs` for the actor

#### Scenario: A runtime with an endpoint
- **WHEN** a `run/start`'s runtime has the endpoint `http://127.0.0.1:11434`
- **THEN** it is refused with `mistralrs.invalid-runtime`, naming `runtime.endpoint`

#### Scenario: A runtime with a credential
- **WHEN** a `run/start`'s runtime has `credential` `true`, and `TROUPE_RUNTIME_CREDENTIAL` holds a canary
- **THEN** it is refused with `mistralrs.invalid-runtime`, naming `runtime.credential`, and the error holds no part
  of the canary

### Requirement: The model is a local GGUF file
The run's model SHALL be an absolute path to a readable GGUF file. A model that isn't an absolute path, or whose file
doesn't start with the GGUF signature, SHALL be refused with `mistralrs.invalid-model`, and a path with no file with
`mistralrs.model-not-found`, each naming the model and `TROUPE_RUNTIME_MISTRALRS_MODEL`. The runner SHALL NOT fetch a
model.

#### Scenario: A model name rather than a file
- **WHEN** the run's model is `Qwen/Qwen3-0.6B-GGUF`
- **THEN** `run/start` is refused with `mistralrs.invalid-model`, saying the model must be the absolute path of a GGUF
  file, and nothing is fetched

#### Scenario: A file that isn't there
- **WHEN** the run's model is `/models/missing.gguf` and no such file exists
- **THEN** `run/start` is refused with `mistralrs.model-not-found`, naming the path

#### Scenario: A file that isn't GGUF
- **WHEN** the run's model is the absolute path of a text file
- **THEN** `run/start` is refused with `mistralrs.invalid-model`, saying the file isn't GGUF

### Requirement: An unsupported macOS Python is refused before the run is acknowledged
On macOS, before answering `run/start`, the runner SHALL load the small model its package carries. When the engine
can't compile its Metal kernels under this Python, it SHALL refuse with `mistralrs.unsupported-python`, naming the
Python, whose fix says to install troupe on a uv-managed Python.

#### Scenario: Kernels that don't compile
- **WHEN** loading the packaged model on macOS fails because the engine's Metal library doesn't compile
- **THEN** `run/start` is refused with `mistralrs.unsupported-python`, naming the Python's path and version, and its
  fix names `uv tool install --managed-python`

#### Scenario: Another platform
- **WHEN** the runner starts a run on Linux or Windows
- **THEN** it loads no packaged model before answering `run/start`

### Requirement: The protocol channel carries only protocol messages
Before it loads the engine, the runner SHALL keep its standard output for the contract's messages and send whatever
the engine writes to standard output to standard error instead.

#### Scenario: The engine's log lines
- **WHEN** a run on the packaged model starts with standard output a pipe, and ends
- **THEN** every line on its standard output is a contract message, and the engine's log lines are on its standard
  error

### Requirement: The model loads after the run is acknowledged, within a named limit
After acknowledging `run/start`, the runner SHALL load the model on a worker thread, saying so in a `log` event, while
it goes on reading troupe's messages. A load that fails, or takes longer than a named limit, SHALL end the run with an
`error` result, reason `configuration`, holding the engine's message.

#### Scenario: An architecture the engine doesn't support
- **WHEN** the engine refuses to load the model file
- **THEN** the run ends with an `error` result, reason `configuration`, holding the engine's message, and no request
  is made

#### Scenario: End of input during the load
- **WHEN** the runner's standard input closes while the model loads
- **THEN** the runner exits within its grace, with no further event

### Requirement: The character and the direction start the conversation
The first request SHALL hold the character as a `system` message, when the actor has one, then the direction as a
`user` message, each unchanged. An actor with no character SHALL have no `system` message.

#### Scenario: An actor with a character
- **WHEN** a run starts with a character and a direction
- **THEN** the first request's messages are a `system` message holding the character and a `user` message holding the
  direction, in that order

#### Scenario: An actor with no character
- **WHEN** a run starts with no character
- **THEN** the first request's only message is the `user` message holding the direction

### Requirement: Every request offers the SDK's tools and nothing of the engine's own
Every request SHALL offer the SDK's tool definitions for the run's scratch directory as function tools, with the
options' `temperature`, `seed` and `think` when set. It SHALL use none of the engine's own tools, tool loop, search or
code execution, and SHALL NOT ask the engine to truncate.

#### Scenario: The tools offered
- **WHEN** a run makes its first request
- **THEN** the request offers one function per SDK tool, with the SDK's name, description and input schema, and
  `Write`'s description names the scratch directory

#### Scenario: Nothing of the engine's own
- **WHEN** any request is made
- **THEN** it enables no engine tool, search or code execution, sets no tool callback, and doesn't ask to truncate

### Requirement: The runner always sets the context window
The run's context window SHALL be `contextLength` when the options set it, and otherwise a named default lowered to the
model's own length. A `contextLength` above the model's length SHALL end the run with `error`, reason `configuration`,
naming both. On Metal, the window SHALL also be the engine's KV budget.

#### Scenario: No context length in the options
- **WHEN** a run starts without `contextLength`, for a model whose length is above the default
- **THEN** the run's window is the runner's default

#### Scenario: A model with a smaller length
- **WHEN** a run starts without `contextLength`, for a model whose length is below the default
- **THEN** the run's window is the model's length

#### Scenario: The KV budget on Metal
- **WHEN** a run with `contextLength` 8192 loads its model on macOS
- **THEN** the engine's KV budget is 8192 tokens

### Requirement: One tool result fits the context window
Each tool result the runner sends the model SHALL be at most a named share of the run's window, counted in bytes at a
named estimate of bytes per token. The runner SHALL lower the SDK's tool limits to fit, and SHALL cut a result still
over it, adding a note that says it was cut to fit the window and how to narrow the call.

#### Scenario: A large file read
- **WHEN** a run with the default window reads a 200 KB text file
- **THEN** the `tool` message holds the file's first lines up to the budget, saying where it stopped and that
  `offset` reads on, and the run goes on

### Requirement: Each answer is bounded by the room left in the window
Before each request the runner SHALL count the conversation's tokens with the model's tokenizer, and SHALL ask for at
most the room the window has left. A conversation with no room left SHALL NOT be sent.

#### Scenario: The room left
- **WHEN** a run's window is 8192 and the conversation counts 6000 tokens
- **THEN** the request asks for at most the 2192 tokens left, less the runner's named margin

#### Scenario: No room left in a run told fail
- **WHEN** a run told `fail` has a conversation that counts more than its window
- **THEN** no request is made, and the run ends with `error` and reason `context-length`, naming the window and
  `contextLength`

### Requirement: A run never carries on past its context window
An answer that stops at the room left, or a request the engine refuses as longer than the model's length or its KV
budget, SHALL end a run told `fail` with an `error` result, reason `context-length`, naming the window and
`contextLength`. That answer's tool calls SHALL NOT be carried out, and the request SHALL NOT be retried.

#### Scenario: An answer that fills the window
- **WHEN** an answer ends with `finish_reason` `length`
- **THEN** its text is still a `turn`, none of its tool calls is carried out, no further request is made, and the run
  ends with `context-length`

#### Scenario: The engine's refusal
- **WHEN** the engine refuses a request because the sequence exceeds its KV capacity
- **THEN** the run ends with `error` and reason `context-length`, holding the engine's message

### Requirement: A run told compact removes old tool results before a request that wouldn't fit
In a run told `compact`, before each request whose count is over a named share of the window, the runner SHALL replace
old tool results with the SDK's stub, oldest first, until the count is at or below a lower named share, and SHALL send a
`context` event before that request.

#### Scenario: A run that reads more than the window holds
- **WHEN** a run told `compact` with a small `contextLength` reads several files in turn
- **THEN** a later request's oldest `tool` messages hold the SDK's stub in place of their output, and the run ends `ok`

#### Scenario: What is never removed
- **WHEN** a run told `compact` compacts its conversation
- **THEN** the `system` message, the first `user` message, every `assistant` message and the latest turn's `tool`
  messages are sent unchanged

#### Scenario: The event before the request
- **WHEN** a run told `compact` compacts its conversation
- **THEN** the runner sends one `context` event with `kind` `truncated` and `by` `runner` before the next turn's events

### Requirement: A run told compact compacts after a refusal and asks again
When the engine refuses a request of a run told `compact` as too long, or an answer stops at the room left, the runner
SHALL compact as before a request and ask again, which SHALL NOT count as a turn. With nothing left to remove, the run
SHALL end with `context-length`.

#### Scenario: Nothing left to remove
- **WHEN** the engine refuses a request of a run told `compact` whose only tool results are the latest turn's
- **THEN** no `context` event is sent, and the run ends with `error` and `reason` `context-length`, saying compaction
  found nothing more to remove

### Requirement: Each tool call is carried out by the SDK and its result sent back
Each tool call in an answer SHALL be carried out with the SDK's tools for the run's declaration, in the order the
answer gives them, and its output, error or not, sent back in the next request as a `tool` message naming the call. A
call with no id SHALL get one the runner makes, unique in the run.

#### Scenario: A call the effects refuse
- **WHEN** the actor declares no effects and the model calls `Delete` on `README.md`
- **THEN** `README.md` still exists, and the next request ends with a `tool` message holding the SDK's refusal,
  naming the `delete` effect

#### Scenario: Two calls in one answer
- **WHEN** one answer holds a `Read` call and then a `Grep` call
- **THEN** both are carried out in that order, and the next request ends with their two `tool` messages in that order

### Requirement: The loop ends when the model stops calling tools
The runner SHALL keep making requests while answers hold tool calls. An answer with no tool call SHALL end the run with
an `ok` result whose message is the answer's text. Reaching `maxTurns` requests, by default a named setting, SHALL end
it with an `error` result, reason `turn-limit`.

#### Scenario: A final answer
- **WHEN** the model's answer holds text and no tool call, and ends with `finish_reason` `stop`
- **THEN** the runner sends an `ok` `result` whose message is that text, and makes no further request

#### Scenario: The turn limit
- **WHEN** `maxTurns` is 2 and both answers hold tool calls
- **THEN** after carrying out the second answer's calls the runner sends an `error` `result` with reason
  `turn-limit`, naming the limit of 2, and makes no third request

### Requirement: Answers map to turns and tool calls
Each answer's text SHALL be one `turn` event with role `assistant`, sent only when the text isn't empty, followed by a
`tool_call` and `tool_result` pair for each call carried out. The model's reasoning SHALL appear only in the
transcript.

#### Scenario: An answer with text and a call
- **WHEN** an answer holds the text `Reading it.` and one `Read` call
- **THEN** the runner sends one `turn` holding `Reading it.`, then that call's `tool_call` and `tool_result`

#### Scenario: Reasoning
- **WHEN** an answer holds reasoning and no text
- **THEN** no `turn` event is sent for it, and its reasoning is in the transcript

### Requirement: The result carries the run's counts
The `result` SHALL carry the number of requests as `turns`, the run's duration, and as `usage` the engine's prompt and
completion token counts summed over every request, as `inputTokens` and `outputTokens`. It SHALL carry no cost and no
cache counter.

#### Scenario: Two requests
- **WHEN** a run's two requests report prompt counts 186 and 208, and completion counts 21 and 16
- **THEN** its `result` has `turns` 2 and `usage` `{"inputTokens": 394, "outputTokens": 37}`, and no `costUsd`

### Requirement: Each failed run reports its reason
Every `error` result SHALL carry a reason from one table in the runner: a full window `context-length`, a model that
won't load or a window it can't hold `configuration`, the turn limit `turn-limit`, any other engine error `engine`, the
runner's own unexpected failure `runner`. No failure SHALL be retried.

#### Scenario: An engine error
- **WHEN** the engine raises an error that isn't about the sequence's length during a request
- **THEN** the run ends with `error` and reason `engine`, holding the engine's message, and sends no `retry` event

#### Scenario: The runner fails
- **WHEN** the runner raises an exception it didn't expect during a run
- **THEN** the `result` has `reason` `runner`

### Requirement: Every exchange with the engine is a transcript record
Before any event they lead to, the runner SHALL send as transcript records the first request as passed to the
engine, then before each later request each message it added and that request's settings (`sent` when it uses
kinds), and each response as the engine returned it (`received`), all serialised. It SHALL NOT resend history.

#### Scenario: A run with one tool call
- **WHEN** a run's first answer calls `Read` once and its second answer ends the run
- **THEN** its transcript is the first request, the first response, the assistant and `tool` messages the runner
  added, the second request's settings (its `max_tokens`), and the second response, in that order, with kinds
  `sent`, `received`, `sent`, `sent`, `sent`, `received`

### Requirement: The mistralrs runner uses transcript kinds
The runner SHALL accept `transcript-kinds` when troupe offers it, and otherwise SHALL send the same records without a
kind.

#### Scenario: No capability offered
- **WHEN** `initialize` offers no capabilities
- **THEN** the runner answers with none, and sends the same transcript records with no kind

### Requirement: Summaries fit below the event limit
Every event's text SHALL be cut on a character boundary so the event fits `limits.eventMaxBytes`, saying how many bytes
were left out, and a `tool_result`'s `outputBytes` SHALL be the full output's size.

#### Scenario: A long final answer
- **WHEN** the final answer's text is 200 KB and `eventMaxBytes` is 65536
- **THEN** the `result` event's encoded size is at most 65536 bytes, and its message ends saying how much was left out

### Requirement: Cancel and end of input end the process at once
On `run/cancel`, end of input or `shutdown`, the runner SHALL carry out no further tool call, send no event after its
acknowledgement, and exit within a named grace well below troupe's own, abandoning any engine call in flight.

#### Scenario: Cancel while the engine answers
- **WHEN** troupe sends `run/cancel` while the packaged model is generating an answer
- **THEN** the runner acknowledges it, sends no further event, and exits within its grace

#### Scenario: End of input while the engine reads a long prompt
- **WHEN** the runner's standard input closes while the packaged model reads a long prompt
- **THEN** the runner exits within its grace

### Requirement: The runner publishes its schemas
The runner SHALL publish `options.schema.json` and `errors.schema.json` in its package, passing the protocol's
strictness check, and its options parser SHALL accept and refuse exactly the options its published schema does.

#### Scenario: Parser and schema agree
- **WHEN** generated option objects are given to the runner's parser and to its published options schema
- **THEN** each object is accepted by both or refused by both

### Requirement: The runner conforms to the contract
The runner SHALL pass troupe's conformance suite with a stand-in for the engine that serves a short successful run.

#### Scenario: The conformance suite
- **WHEN** the conformance suite runs against the runner with the engine stand-in and the runtime `mistralrs`
- **THEN** every check passes

### Requirement: Fixtures pair real engine output with protocol events
The plugin SHALL hold fixtures captured from a real model by a capture tool, each with its provenance (the
`mistralrs` version, the model and the date), the responses it recorded, and the run events the runner maps them to. A
test SHALL check that replaying each through the engine stand-in gives exactly its events.

#### Scenario: A fixture replayed
- **WHEN** a fixture's recorded responses are served by the engine stand-in to the runner
- **THEN** the runner sends exactly the fixture's events and transcript records

### Requirement: Tests load no downloaded model
The plugin's tests SHALL use only the small model its package carries and the recorded fixtures. A test against a
real model SHALL run only when `TROUPE_LIVE_MISTRALRS` names a model file, and SHALL otherwise be reported skipped,
naming the variable. CI SHALL NOT set it.

#### Scenario: Without the variable
- **WHEN** the tests run without `TROUPE_LIVE_MISTRALRS`
- **THEN** the live test is skipped with a reason naming `TROUPE_LIVE_MISTRALRS`
