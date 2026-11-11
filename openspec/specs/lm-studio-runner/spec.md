# lm-studio-runner Specification

## Purpose
Capability: `cap:actor-runners`

An actor runner for a model served by LM Studio, through LM Studio's own client library: the library runs the model's
rounds, troupe carries out and checks each tool call against the actor's declared effects, and the service comes from
the actor's runtime.

## Requirements

### Requirement: The LM Studio runner is a self-contained plugin
The runner SHALL be a plugin in `plugins/runner-lm-studio`, with its own package, tests and release component, run
over JSON-RPC, that imports nothing of troupe's but the plugin SDK.

#### Scenario: Its imports
- **WHEN** the import-linter contracts are checked
- **THEN** `troupe_runner_lm_studio` imports nothing from `troupe` and nothing from another plugin

#### Scenario: troupe starts it by name
- **WHEN** an actor's runner is `lm-studio` and its extra is installed
- **THEN** perform starts the runner's module over JSON-RPC, with no variable from the person's environment

### Requirement: The runner talks to LM Studio only through the lmstudio package
The runner SHALL reach LM Studio only through LM Studio's `lmstudio` client package, at the version its lock file pins,
and SHALL open no other connection to LM Studio.

#### Scenario: The pinned library
- **WHEN** the plugin's dependencies are read
- **THEN** they are the plugin SDK and `lmstudio`, and `uv.lock` pins `lmstudio` and every package it depends on

### Requirement: The library's dependencies are licensed and installable everywhere troupe runs
Every package the runner depends on, directly or not, SHALL have a licence compatible with Apache-2.0, and SHALL
install on Linux, macOS and Windows for every Python version troupe supports.

#### Scenario: Licences
- **WHEN** the licences of the runner's locked dependencies are checked
- **THEN** each is a licence compatible with Apache-2.0

#### Scenario: Installs
- **WHEN** CI installs the runner's extra on Linux, macOS and Windows, on each supported Python
- **THEN** each install succeeds

### Requirement: The runner identifies itself as lm-studio
The runner's handshake and `init` event SHALL name the runner `lm-studio`. Its `init` event's `engine.name` SHALL be
`lm-studio`, its `engine.model` the run's model, its `tools` the SDK's tool names, and its `effects` `checked`.

#### Scenario: Init
- **WHEN** a run on the model `qwen/qwen3-4b` starts
- **THEN** its `init` event names the runner `lm-studio`, `engine.name` `lm-studio`, `engine.model` `qwen/qwen3-4b`,
  the tools `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Delete` and `Move`, and `effects` `checked`

### Requirement: The service comes from the run's runtime
The runner SHALL take the endpoint and the model from the runtime troupe resolves for the run, and from nowhere else.
Its options SHALL hold no endpoint or model, and the runner SHALL hard-code neither.

#### Scenario: A run without a runtime
- **WHEN** a `run/start` carries no runtime
- **THEN** `run/start` is refused with `lm-studio.no-runtime`, whose fix says to name a runtime for the actor

#### Scenario: An endpoint in the options
- **WHEN** a `run/start`'s options hold `endpoint` or `model`
- **THEN** `run/start` is refused with `lm-studio.unknown-option`, naming the option

#### Scenario: The runtime's model is used
- **WHEN** a run's runtime names the model `small-model`
- **THEN** the pre-run check looks for `small-model`, and the run's predictions use `small-model`

### Requirement: The runtime's endpoint is the library's host and port
The runner SHALL give the library the endpoint's host and port, always, so the library never looks for LM Studio
itself. An endpoint without an explicit port SHALL use port 80, as `http` does.

#### Scenario: The built-in runtime
- **WHEN** a run's runtime has the endpoint `http://127.0.0.1:1234`
- **THEN** the library connects only to `127.0.0.1:1234`, and to no other port

#### Scenario: No LM Studio at the endpoint
- **WHEN** nothing listens at the endpoint, but an LM Studio listens on one of the library's default ports
- **THEN** `run/start` is refused with `lm-studio.unreachable`, and nothing connects to the default port

### Requirement: An endpoint the library can't use is refused
A runtime endpoint that is `https`, or has a path other than `/`, SHALL be refused with
`lm-studio.unsupported-endpoint`, naming the endpoint and why, before anything is sent. For a path, the fix SHALL give
the endpoint without it.

#### Scenario: The OpenAI-compatible base
- **WHEN** a run's runtime has the endpoint `http://127.0.0.1:1234/v1`
- **THEN** `run/start` is refused with `lm-studio.unsupported-endpoint`, whose fix names `http://127.0.0.1:1234`

#### Scenario: HTTPS
- **WHEN** a run's runtime has the endpoint `https://lm.example.com`
- **THEN** `run/start` is refused with `lm-studio.unsupported-endpoint`, saying the library connects only over plain
  `ws://`, and nothing is sent

### Requirement: A runtime with a credential is refused
When `run/start`'s `runtime.credential` is `true`, the runner SHALL refuse it with `lm-studio.credential-unsupported`,
saying the library can't send an LM Studio API token, before anything is sent. The error SHALL hold no part of the
value.

#### Scenario: A token in the runtime
- **WHEN** `runtime.credential` is `true` and `TROUPE_RUNTIME_CREDENTIAL` holds a token
- **THEN** `run/start` is refused with `lm-studio.credential-unsupported`, its fix says to turn off LM Studio's
  "Require Authentication" or remove the runtime's credential, and the error holds no part of the token

#### Scenario: A token run start doesn't mention
- **WHEN** `runtime.credential` is `false` and `TROUPE_RUNTIME_CREDENTIAL` holds a value
- **THEN** `run/start` is refused with `lm-studio.credential-mismatch`, and the error holds no part of the value

### Requirement: The runner's options are closed
`run/start` options SHALL be an object with only `maxTurns`, `maxTotalTokens` and `contextLength` (positive integers)
and `temperature` (a number from 0 to 1), each optional. An unknown option SHALL be refused with
`lm-studio.unknown-option`, and a bad value with `lm-studio.invalid-options`.

#### Scenario: An unknown option
- **WHEN** the options hold `troupeConformanceUnknownOption`
- **THEN** `run/start` is refused with `lm-studio.unknown-option`, whose `details.where` names the option

#### Scenario: A malformed value
- **WHEN** `maxTurns` is `0` or `temperature` is `1.5`
- **THEN** `run/start` is refused with `lm-studio.invalid-options`, naming the option, and its fix names what is valid

#### Scenario: No options
- **WHEN** a run starts with empty options
- **THEN** its turn limit, token budget and context length are the runner's named defaults, and no temperature is set

### Requirement: The runner checks LM Studio before it acknowledges the run
Before answering `run/start`, the runner SHALL connect to LM Studio and ask for its downloaded models within a named
time limit, refusing the run with `lm-studio.unreachable` when LM Studio doesn't answer, and `lm-studio.incompatible`
when it answers but the library can't list its models, naming the LM Studio version the runner was tested with.

#### Scenario: LM Studio isn't running
- **WHEN** nothing listens at the endpoint
- **THEN** `run/start` is refused with `lm-studio.unreachable`, naming the endpoint, and the fix says to start
  LM Studio's server (`lms server start`) or set the runtime's endpoint

#### Scenario: An LM Studio the library can't talk to
- **WHEN** the endpoint answers LM Studio's greeting, but listing the models fails
- **THEN** `run/start` is refused with `lm-studio.incompatible`, naming the library's error and the LM Studio version
  from the runner's published requirements, and the fix says to upgrade LM Studio

### Requirement: The pre-run check finds a model that can call tools
The pre-run check SHALL refuse the run with `lm-studio.model-not-found` when no downloaded LLM's key is the run's model,
and with `lm-studio.model-without-tools` when that model isn't trained for tool use.

#### Scenario: A model that isn't downloaded
- **WHEN** LM Studio's downloaded models don't include `qwen/qwen3-4b`
- **THEN** `run/start` is refused with `lm-studio.model-not-found`, and the fix names `lms get qwen/qwen3-4b`

#### Scenario: A model that can't call tools
- **WHEN** the model's info says it isn't trained for tool use
- **THEN** `run/start` is refused with `lm-studio.model-without-tools`, naming the model

### Requirement: The runner publishes its platform requirements as data
The runner SHALL publish what it requires of LM Studio as data in its package, beside its schemas, with the thing
required, the least version and why, and its refusals SHALL name the version from that data, not from its code.
LM Studio reports no version, so the least version is the one the runner was tested with.

#### Scenario: The published requirement
- **WHEN** the runner's published requirements are read
- **THEN** they hold `lm-studio` at least `0.4.28`, with a reason naming the `lmstudio` package's version and that
  LM Studio reports no version to check

### Requirement: The model is loaded with the run's context length, and the length is reported
When the run's model isn't loaded, the runner SHALL load it with the run's context length, reporting load progress as
`log` events. When it's already loaded, the runner SHALL use it as it is, and SHALL report its context length in a
`log` event when that differs from the run's.

#### Scenario: A model not yet loaded
- **WHEN** a run with `contextLength` 16384 starts on a model that isn't loaded
- **THEN** the model is loaded with a context length of 16384, and the run reports the load's progress

#### Scenario: A model loaded with another length
- **WHEN** the model is already loaded with a context length of 4096 and the run asks for 16384
- **THEN** the run uses the loaded model and reports, in a `log` event, that its context length is 4096, not 16384

### Requirement: The character is the system prompt and the direction the first message
The run's chat SHALL start with a system prompt made of the runner's fixed instructions followed by the actor's
character when it has one, then one user message holding the direction unchanged.

#### Scenario: An actor with a character
- **WHEN** a run starts with the character `You are terse.` and the direction `Write out/hello.txt`
- **THEN** the chat's system prompt ends with `You are terse.`, and its one user message is `Write out/hello.txt`

#### Scenario: An actor without a character
- **WHEN** a run starts with no character
- **THEN** the system prompt holds only the runner's fixed instructions

### Requirement: The model is offered the SDK's tools
The run SHALL offer the model exactly the plugin SDK's tools, in its order, each with the SDK's name and description,
and each parameter with its SDK name, type, description, whether it's required, and its minimum.

#### Scenario: The tools offered
- **WHEN** the tools the library sends LM Studio are read from the run's transcript
- **THEN** they are `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Delete` and `Move`, in that order, and each one's
  parameters are the SDK's input schema without `additionalProperties`, which the library can't send

#### Scenario: An optional parameter
- **WHEN** the schema of `Read`'s `offset` is read
- **THEN** it is an integer with the SDK's description and minimum 1, not nullable, and not required

### Requirement: Each tool call is carried out by the SDK and checked against the effects
Each tool call the library makes SHALL be carried out by the plugin SDK, which checks it against the actor's declared
effects first, one at a time in the order the model asked, and reported as a `tool_call` and `tool_result` pair.

#### Scenario: A write the actor didn't declare
- **WHEN** a read-only actor's model asks to `Write` `out/hello.txt`
- **THEN** the file isn't written, the model gets an error result naming the `write` effect, and the run reports a
  `tool_call` and an error `tool_result`

#### Scenario: Two calls in one round
- **WHEN** the model asks for `Read` and then `Grep` in one round
- **THEN** `Read` is carried out and reported before `Grep` starts

### Requirement: A call the library rejects is answered as troupe would answer it
A call the library rejects before carrying it out (an unknown tool, or arguments that don't fit the tool's
parameters) SHALL be answered with the SDK's own error for that input, reported as a `tool_call` and an error
`tool_result`, and the run SHALL go on.

#### Scenario: A call to a tool that doesn't exist
- **WHEN** the model asks for `Bash`
- **THEN** the run reports a `tool_call` for `Bash` and an error `tool_result` with the SDK's message for an unknown
  tool, the model gets that message, and the run goes on

#### Scenario: A required argument missing
- **WHEN** the model asks for `Read` without `file_path`
- **THEN** the model gets the SDK's message that `Read` needs `file_path`, and the run reports it as an error
  `tool_result`

### Requirement: Every run has a turn limit and a token budget
A run SHALL make at most `maxTurns` rounds and SHALL start no round once it has used `maxTotalTokens` tokens, the sum
of each round's prompt and predicted tokens. Reaching either SHALL end the run with an `error` result saying which.

#### Scenario: The turn limit is reached
- **WHEN** a run with `maxTurns` 3 gets a tool call in each of its three rounds
- **THEN** each round is offered the tools, the third round's calls are carried out, no fourth round starts, and the
  run ends with an `error` result saying the turn limit of 3 was reached

#### Scenario: A run that finishes on its last allowed round
- **WHEN** a run with `maxTurns` 3 gets a tool call in each of its first two rounds, and a reply without one in its
  third
- **THEN** the run ends with an `ok` result whose message is the third round's text

#### Scenario: The token budget is spent
- **WHEN** a run with `maxTotalTokens` 1000 has used 1200 tokens after a round that asked for a tool call
- **THEN** that round's call is carried out, no further round starts, and the run ends with an `error` result saying
  the token budget of 1000 was spent, with the tokens used

### Requirement: Assistant text is reported as turns
The answer text a round streams SHALL be reported as a `turn` when the round's first tool call starts, and any after
that when the round ends, so each turn comes before the calls that follow it. Empty text SHALL report no turn, and
text the library marks as reasoning SHALL NOT be in a turn.

#### Scenario: Text and a tool call
- **WHEN** a round streams text and then asks for one tool call, and the next round streams only text
- **THEN** the run reports a `turn`, the call's pair, and another `turn`, in that order

#### Scenario: Reasoning
- **WHEN** a round streams reasoning before its text, and the round's result holds both in its content
- **THEN** no `turn` holds the reasoning or its start and end tags

### Requirement: A round without a tool call ends the run
A round whose prediction asks for no tool call SHALL end the run with an `ok` result whose message is that round's
text, unless the prediction stopped for a reason other than its natural end.

#### Scenario: A run that finishes
- **WHEN** a round's prediction asks for no tool and its text is `Done.`
- **THEN** the run ends with an `ok` result whose message is `Done.`

#### Scenario: A prediction cut short by the context
- **WHEN** a round's prediction stops because the context length was reached
- **THEN** the run ends with an `error` result saying the context length was reached, naming it

### Requirement: The result carries the run's counts
The result SHALL report the sum of each round's prompt tokens as input tokens and predicted tokens as output tokens,
no cache counters, and the number of rounds the run made as its `turns`. It SHALL report no `costUsd`, since LM Studio
reports no cost.

#### Scenario: Counts from two rounds
- **WHEN** a run's two rounds report 1000 and 1300 prompt tokens and 100 and 200 predicted tokens
- **THEN** the result reports 2300 input tokens, 300 output tokens, `turns` 2 and no `costUsd`

### Requirement: A cost is estimated only from run start's price
When `run/start`'s runtime carries a price, the result SHALL carry `estimatedCostUsd`, the run's input and output
tokens at that price, unless the price has a rate for a counter LM Studio doesn't report. Without a price, the result
SHALL carry no estimate.

#### Scenario: A price
- **WHEN** a run with the price `{"input": 2, "output": 8}` uses 1,000,000 input and 500,000 output tokens
- **THEN** its result carries `estimatedCostUsd` 6

#### Scenario: A price with a cache rate
- **WHEN** a run's price has a `cacheRead` rate
- **THEN** its result carries no `estimatedCostUsd`, since LM Studio reports no cache reads

#### Scenario: No price
- **WHEN** a run's `run/start` carries no price
- **THEN** its result carries no `estimatedCostUsd`

### Requirement: Every error result names its reason
Every `error` result SHALL carry the contract's `reason`: `turn-limit` for the turn limit, `budget` for the token
budget, `context-length` when the context was reached, `output-limit` when the predicted-token limit was, `network`
for a lost connection or a timeout, `engine` when the model was unloaded or the prediction failed, and `other` for
anything else, its message saying what happened. After `run/cancel` the runner sends no result.

#### Scenario: Each ending's reason
- **WHEN** runs end at the turn limit, at the token budget, at the context length, after a connection retried until
  its attempts ran out, and after the model was unloaded
- **THEN** their results' reasons are `turn-limit`, `budget`, `context-length`, `network` and `engine`

#### Scenario: A stop reason the runner doesn't know
- **WHEN** a round's prediction stops with a reason the runner doesn't map, or one LM Studio's library refuses
- **THEN** the run ends with an `error` result, `reason` `other`, whose message names that stop reason

### Requirement: A model other than the run's is reported
When the loaded model, or a round's result, names a model key other than the run's model, the runner SHALL send
`served_model` with that key the first time it's named, before any turn it answers, and a key outside the contract's
shape as a `log` warning instead.

#### Scenario: The model asked for answers
- **WHEN** every round's result names the run's model
- **THEN** the run has no `served_model` event

### Requirement: LM Studio's failures end the run as error results
A failure the library raises during a run, other than a retried one, SHALL end the run with an `error` result naming
what failed and the library's message, cut to fit the event limit.

#### Scenario: The model is unloaded mid-run
- **WHEN** a round's prediction stops because the model was unloaded
- **THEN** the run ends with an `error` result saying the model was unloaded

### Requirement: A connection is retried only before any tool call has run
A connection failure or a lost connection SHALL be retried, with a `retry` event each time, within a named number of
attempts, only while no tool call has run, and the library SHALL retry nothing itself. After a call has run, it SHALL
end the run with an `error` result saying a retry could run a tool twice.

#### Scenario: A lost connection before any tool call
- **WHEN** the first round's connection drops, and the second attempt succeeds
- **THEN** the run reports one `retry` event, then goes on

#### Scenario: A lost connection after a tool call
- **WHEN** the connection drops after a `Write` call was carried out
- **THEN** nothing is retried, and the run ends with an `error` result saying a retry could run a tool twice

### Requirement: Every limit the library applies is one of the runner's named settings
Each timeout the library applies (the greeting check, waiting for a server message, closing the websocket) SHALL be
set from one of the runner's named settings, never left to the library's default. Where the library offers no way to
set one, the runner's own named deadline SHALL bound the call.

#### Scenario: A server that never answers
- **WHEN** the fake endpoint accepts the websocket and then sends nothing, and the message timeout setting is 2 seconds
- **THEN** the run ends with an `error` result naming the timeout within the setting plus the runner's grace, not the
  library's default

### Requirement: Redirects are never followed
A redirect from LM Studio's endpoint SHALL refuse `run/start` with `lm-studio.unreachable`, naming the status and where
it pointed, and SHALL NOT be followed.

#### Scenario: A redirect
- **WHEN** the endpoint answers the library's first request with 307 to another address
- **THEN** `run/start` is refused naming 307 and the address, and nothing connects to that address

### Requirement: The transcript is what the library exposes
The runner SHALL accept `transcript-kinds`, and send as transcript records, before any event they lead to and each
serialised as the library gives it: the downloaded model's info (`received`), the chat and tools the run passes the
library (`sent`), each round's result with its stats (`received`), and each tool result message (`sent`).

#### Scenario: A run with one tool call
- **WHEN** a run's first round asks for one tool call and its second round ends the run
- **THEN** its transcript holds the model's info (`received`), the chat and tools (`sent`), the first round's result
  (`received`), the tool result message (`sent`) and the second round's result (`received`), in that order

#### Scenario: A host that offers no kinds
- **WHEN** `initialize` offers no `transcript-kinds`
- **THEN** the runner sends the same records with no kind

### Requirement: The library's own logging stays out of the run's output
The library's log output SHALL NOT reach standard output, and SHALL reach standard error only at warning level or
above, cut to fit the event limit.

#### Scenario: The library logs a prediction
- **WHEN** the library logs at debug level during a run
- **THEN** nothing it logged appears on standard output or standard error

### Requirement: Summaries fit below the event limit
Every event's text SHALL be cut on a character boundary so the event fits `limits.eventMaxBytes`, saying how many bytes
were left out, and a `tool_result`'s `outputBytes` SHALL be the full output's size.

#### Scenario: A long final message
- **WHEN** the final round's text is 200 KB and `eventMaxBytes` is 65536
- **THEN** the `result` event's encoded size is at most 65536 bytes, and its message ends saying how much was left out

### Requirement: Cancel and end of input stop the run at once
On `run/cancel`, end of input, or `shutdown`, the runner SHALL stop the prediction in flight, carry out no further tool
call, send no further event, and exit within a named grace well below troupe's own.

#### Scenario: Cancel while the model predicts
- **WHEN** troupe sends `run/cancel` while the fake endpoint streams a prediction slowly
- **THEN** the runner acknowledges it, the fake endpoint sees the prediction cancelled or its connection closed, no
  event follows the acknowledgement, and the runner exits within its grace

#### Scenario: A tool call after cancel
- **WHEN** the library asks for a tool call after `run/cancel`
- **THEN** the call isn't carried out

### Requirement: The runner publishes its schemas
The runner SHALL publish `options.schema.json` and `errors.schema.json` in its package, passing the protocol's
strictness check, and its options parser SHALL accept and refuse exactly the options its published schema does.

#### Scenario: Parser and schema agree
- **WHEN** generated option objects are given to the runner's parser and to its published options schema
- **THEN** each object is accepted by both or refused by both

### Requirement: The runner conforms to the contract
The LM Studio runner SHALL pass troupe's conformance suite against a fake LM Studio endpoint.

#### Scenario: The conformance suite
- **WHEN** the conformance suite runs against the LM Studio runner, on a runtime naming a fake endpoint that serves a
  short successful run
- **THEN** every check passes

### Requirement: Fixtures pair real LM Studio exchanges with protocol events
The plugin SHALL hold fixtures captured from a real LM Studio by a capture tool, each with its provenance (LM Studio's
version, the library's version, the model and the date), the exchange it recorded, and the events the runner maps it
to. A test SHALL replay each through the fake endpoint and check its events.

#### Scenario: A fixture replayed
- **WHEN** a fixture's recorded exchange is served by the fake endpoint to the runner
- **THEN** the runner sends exactly the fixture's events and transcript records

### Requirement: A live test runs a real model only when asked
A test against a real LM Studio SHALL run only when `TROUPE_LIVE_LM_STUDIO=1` is set, and SHALL otherwise be reported
skipped, naming the variable. CI SHALL NOT set it.

#### Scenario: Without the variable
- **WHEN** the tests run without `TROUPE_LIVE_LM_STUDIO`
- **THEN** the live test is skipped with a reason naming `TROUPE_LIVE_LM_STUDIO`
