# Spec Delta

## Purpose

Capability: `cap:actor-runners`

The Anthropic runner: an actor runner that drives the Anthropic Messages API, served by Claude's own API or by a local
engine, through the `anthropic` package with troupe's own tool loop, so the runner contract is tested by a third API
shape, against a hosted engine and a local one, through a client library the runner holds to troupe's guarantees.

## ADDED Requirements

### Requirement: The Anthropic runner is a self-contained plugin
The runner SHALL live in `plugins/runner-anthropic` with its own package, tests and published schemas, and SHALL
import nothing of troupe's except the plugin SDK. It SHALL identify itself as `anthropic` in its handshake and its
`init` event, and its `init` event's `engine.name` SHALL be `messages`.

#### Scenario: Only the SDK is imported
- **WHEN** the import contracts are checked
- **THEN** no module of the runner imports `troupe` or any package of troupe's other than `troupe_plugin_sdk`

#### Scenario: Its name
- **WHEN** the runner answers `initialize` and a run starts
- **THEN** its name is `anthropic`, its version is the package's version, and its `init` event's `engine.name` is
  `messages`

### Requirement: The runner talks to its service only through the anthropic package
The runner SHALL send every request through the `anthropic` package, pinned to one version in the lock file, as a
streamed call to the Messages API, and SHALL use no other API of the service. One module alone SHALL import the
package.

#### Scenario: The one module that imports it
- **WHEN** the import contracts are checked
- **THEN** exactly one module of the runner imports `anthropic`, and a scratch module elsewhere in the runner that
  imports it fails the check

#### Scenario: Where a request goes
- **WHEN** a run's runtime has the endpoint `http://127.0.0.1:1234`
- **THEN** each request is a `POST` to `http://127.0.0.1:1234/v1/messages` with `stream` true

### Requirement: The library's dependencies are licensed and installable everywhere troupe runs
Every package the runner depends on through `anthropic` SHALL pass the repository's licence check, and SHALL install
on Linux, macOS and Windows for every Python version troupe supports.

#### Scenario: The licence check
- **WHEN** `scripts/check.py` checks the lock file
- **THEN** `anthropic` and every package it pulls in are on a tier of the licence list, any weak-copyleft one from a
  package index

#### Scenario: Every platform
- **WHEN** CI installs `troupe-run[anthropic]` on Linux, macOS and Windows for each supported Python
- **THEN** it installs, and the runner answers `initialize`

### Requirement: The service comes from the run's runtime
The runner SHALL take the endpoint, the model and the credential from the runtime troupe resolves for the run (spec:
runtimes), and from nowhere else. Its options SHALL hold no endpoint, model or credential, and no endpoint or model
SHALL be hard-coded in the runner.

#### Scenario: An endpoint in the options
- **WHEN** a `run/start`'s options hold `endpoint`
- **THEN** `run/start` is refused with `anthropic.unknown-option`, naming `endpoint`

#### Scenario: A run without a runtime
- **WHEN** a `run/start` carries no runtime
- **THEN** `run/start` is refused with `anthropic.no-runtime`, whose fix says to name a runtime for the actor

#### Scenario: The runtime's model is asked for
- **WHEN** a run's runtime names the model `small-model`
- **THEN** every request asks for `small-model`, and the `init` event's `engine.model` is `small-model`

#### Scenario: A local engine through a runtime of your own
- **WHEN** config defines `runtimes.lm-studio-messages.endpoint=http://127.0.0.1:1234` and an `anthropic` actor names
  that runtime and the model `google/gemma-4-e4b`
- **THEN** the actor is accepted, and the run's requests go to `http://127.0.0.1:1234/v1/messages` with no credential

### Requirement: The library finds nothing of its own
The runner SHALL give the library its base URL, its credential or the absence of one, its HTTP client and every
header itself, so that no environment variable or file the library would otherwise read (`ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_CUSTOM_HEADERS`, `ANTHROPIC_PROFILE`, a profile on disk, or
workload identity variables) changes where a request goes or what it carries.

#### Scenario: Variables the library reads
- **WHEN** the runner's environment holds `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` and `ANTHROPIC_CUSTOM_HEADERS`,
  and its runtime has no credential and the endpoint of the fake endpoint
- **THEN** every request reaches the fake endpoint with no `Authorization` or `x-api-key` header and none of the
  custom headers, and no request goes to the variable's base URL

#### Scenario: A profile on disk
- **WHEN** `ANTHROPIC_CONFIG_DIR` names a directory holding an active profile with a token, and the runtime has no
  credential
- **THEN** no request carries that token

### Requirement: The runtime's endpoint is the API's base URL
The runner SHALL refuse `run/start` with `anthropic.unsupported-endpoint`, naming `runtime.endpoint`, when the
runtime's endpoint's path ends in `/v1`, or the endpoint holds a query or a fragment, before any request is sent. The
error SHALL say the library adds `/v1/messages` itself and name the endpoint that would fit, and SHALL NOT repeat an
endpoint that holds user info.

#### Scenario: An OpenAI-style base
- **WHEN** a `run/start`'s runtime endpoint is `http://127.0.0.1:1234/v1`
- **THEN** `run/start` is refused with `anthropic.unsupported-endpoint`, naming `http://127.0.0.1:1234` as the
  endpoint to use, and no request is sent

#### Scenario: A gateway's own path
- **WHEN** a `run/start`'s runtime endpoint is `https://gateway.example/anthropic`
- **THEN** the run's requests go to `https://gateway.example/anthropic/v1/messages`

### Requirement: The credential is read from TROUPE_RUNTIME_CREDENTIAL
The runner SHALL read the run's credential only from `TROUPE_RUNTIME_CREDENTIAL`, and only when `run/start`'s
`runtime.credential` is `true`. When the two disagree, it SHALL refuse `run/start` with `anthropic.credential-mismatch`,
saying which way without the value, and send nothing. A credential holding any character other than visible ASCII
SHALL be refused with `anthropic.malformed-credential`, naming the variable and never the value.

#### Scenario: A credential run start promises and the environment lacks
- **WHEN** `runtime.credential` is `true` and `TROUPE_RUNTIME_CREDENTIAL` isn't set
- **THEN** `run/start` is refused with `anthropic.credential-mismatch`, and no request is sent

#### Scenario: A credential run start doesn't mention
- **WHEN** `runtime.credential` is `false` and `TROUPE_RUNTIME_CREDENTIAL` holds a value
- **THEN** `run/start` is refused with `anthropic.credential-mismatch`, and the error holds no part of the value

#### Scenario: A key read with its line ending
- **WHEN** `TROUPE_RUNTIME_CREDENTIAL` holds a key followed by `\r\n`
- **THEN** `run/start` is refused with `anthropic.malformed-credential`, the error holds no part of the key, and no
  request is sent

### Requirement: The credential goes only in the Authorization header
When the runtime has a credential, the runner SHALL send it as `Authorization: Bearer <credential>` on each request to
the runtime's endpoint, and nowhere else. It SHALL NOT appear in any run event, transcript record, log, error or
standard error output, however the library reports what it did.

#### Scenario: A known credential is nowhere troupe can see
- **WHEN** a run with the credential `sk-ant-canary-0123456789` ends in each way the fake endpoint can make it end
- **THEN** the fake endpoint received it in each request's `Authorization` header and in no other header, and no event,
  transcript record, error or standard error line holds it

#### Scenario: A runtime without a credential
- **WHEN** a run's runtime has no credential
- **THEN** its requests carry neither an `Authorization` nor an `x-api-key` header

#### Scenario: A library error that quotes the request
- **WHEN** the library raises an error whose text holds the request's headers
- **THEN** no event, transcript record or log line the runner writes holds the credential

### Requirement: A service's echo of the credential is masked
Where a service's response repeats the credential, whole or with part of it masked, the runner SHALL replace it with
`[credential]` in everything it sends troupe, the transcript included, before sending it.

#### Scenario: A 401 that quotes part of the key
- **WHEN** the run's credential is `sk-ant-canary-0123456789` and a 401's message quotes `sk-ant-ca*********6789`
- **THEN** the result's message and the transcript's record of that body hold `[credential]` in its place

### Requirement: A credential never travels in the clear
The runner SHALL refuse a `run/start` whose runtime has a credential and an `http` endpoint whose host isn't a
loopback address, with `anthropic.insecure-endpoint` naming the endpoint, and send nothing.

#### Scenario: Plain HTTP to another host
- **WHEN** a run's runtime has a credential and the endpoint `http://models.example.com`
- **THEN** `run/start` is refused with `anthropic.insecure-endpoint`, and no request is sent

#### Scenario: Plain HTTP to this machine
- **WHEN** a run's runtime has a credential and the endpoint `http://127.0.0.1:1234`
- **THEN** the run starts and its requests go to that endpoint

### Requirement: The runner's options are closed
`run/start` options SHALL be an object with only `maxTurns`, `maxTotalTokens`, `maxOutputTokens` and `contextWindow`,
each optional and each a positive integer. An option the runner doesn't define, or a value of the wrong shape, SHALL be
refused with an error naming it, and no request SHALL be sent.

#### Scenario: An unknown option
- **WHEN** the options hold `troupeConformanceUnknownOption`
- **THEN** `run/start` is refused with `anthropic.unknown-option`, whose `details.where` names the option

#### Scenario: A malformed value
- **WHEN** `maxOutputTokens` is `0` or `contextWindow` is `"big"`
- **THEN** `run/start` is refused with `anthropic.invalid-options`, whose `details.where` names the option and whose
  fix names what is valid

### Requirement: Every run has a turn limit and a token budget
The runner SHALL limit a run to `maxTurns` requests, a retried request counting once, and SHALL send no request once
the run has used `maxTotalTokens` tokens, every reply's input, cache and output tokens summed. Each reply is counted
whole after it arrives, so a run can end above its budget. Each limit SHALL default to a named setting in the runner.

#### Scenario: The turn limit is reached
- **WHEN** a run with `maxTurns` 3 gets a tool call in each of its first three replies
- **THEN** the runner carries out the third reply's calls, sends no fourth request, and ends with an `error` result
  saying the turn limit of 3 was reached

#### Scenario: The token budget is spent
- **WHEN** a run with `maxTotalTokens` 1000 has used 1200 tokens after a reply that asks for a tool call
- **THEN** the runner carries out that call, sends no further request, and ends with an `error` result saying the
  token budget of 1000 was spent, with the tokens used

#### Scenario: A last reply past the budget
- **WHEN** a run with `maxTotalTokens` 1000 gets a reply without a tool call that brings its usage to 1200
- **THEN** the run ends with an `ok` result reporting the 1200 tokens

### Requirement: Each request asks for the run's output limit
Each request's `max_tokens` SHALL be `maxOutputTokens`, or the runner's named default when the options don't set it.

#### Scenario: No output limit in the options
- **WHEN** a run starts with empty options
- **THEN** each request's `max_tokens` is the runner's named default

#### Scenario: An output limit in the options
- **WHEN** a run's options set `maxOutputTokens` 2048
- **THEN** each request's `max_tokens` is 2048

### Requirement: The character is the system prompt and the direction the first message
The first request SHALL carry a `system` made of the runner's fixed instructions followed by the actor's character
when it has one, and `messages` holding one user message whose content is the direction unchanged.

#### Scenario: An actor with a character
- **WHEN** a run starts with the character `You are terse.` and the direction `Write out/hello.txt`
- **THEN** the first request's `system` ends with `You are terse.`, and its `messages` are one user message whose
  content is `Write out/hello.txt`

#### Scenario: An actor without a character
- **WHEN** a run starts with no character
- **THEN** the `system` holds only the runner's fixed instructions

### Requirement: The model is offered the SDK's tools
Each request SHALL offer the model the plugin SDK's tool definitions as custom tools, each with its name, description
and input schema unchanged, and the `init` event SHALL list the same tools.

#### Scenario: The tools offered
- **WHEN** the first request is sent
- **THEN** its `tools` are the SDK's tools in the SDK's order, each with its `name`, `description` and
  `input_schema` as the SDK defines them

### Requirement: The runner applies the effects by checking each call
The runner SHALL carry out each tool call the model asks for through the plugin SDK, which checks it against the
actor's declared effects first. Its `init` event's `effects` SHALL be `checked`.

#### Scenario: A write the actor didn't declare
- **WHEN** a read-only actor's model asks to `Write` `out/hello.txt`
- **THEN** the file isn't written, the `tool_result` event is an error naming the `write` effect, and the model is
  sent that result with `is_error` true

### Requirement: Tool calls are carried out in order and answered in the next request
When a reply ends with `stop_reason` `tool_use`, the runner SHALL carry out its `tool_use` blocks one at a time in
order, sending each call's `tool_call` and `tool_result`. The next request's `messages` SHALL be the previous ones,
then an assistant message holding the reply's content blocks unchanged, then one user message with a `tool_result`
per call, in order, each naming its `tool_use_id`.

#### Scenario: Two calls in one reply
- **WHEN** a reply holds a `tool_use` for `Read` `a.txt` and then one for `Read` `b.txt`
- **THEN** the events are the `tool_call` and `tool_result` for `a.txt`, then those for `b.txt`, and the next request
  ends with one user message holding two `tool_result` blocks in that order, each naming its call's id

#### Scenario: Thinking is sent back as the service gave it
- **WHEN** a reply holds a `thinking` block, with its signature, and then a `tool_use`
- **THEN** the next request's assistant message holds that `thinking` block unchanged before the `tool_use`

### Requirement: A malformed tool call is answered, not fatal
A tool call whose streamed input isn't a JSON object, or whose tool isn't one of the SDK's, SHALL be answered with an
error result the model is sent, as the SDK makes it, and the run SHALL go on. The call's block is sent back with an
empty `input`, since the API takes only an object there.

#### Scenario: A tool the SDK doesn't have
- **WHEN** a reply asks to call `Bash`
- **THEN** the `tool_result` is an error naming the tools there are, and the next request carries it with `is_error`
  true

#### Scenario: Input that isn't JSON
- **WHEN** a reply's `tool_use` for `Write` streams the input `{"file_path": "a.txt"`
- **THEN** the `tool_result` is the SDK's error saying the input isn't valid JSON, and the next request carries the call's
  block with `input` `{}` and that result

### Requirement: A finished reply without tool calls ends the run
A reply whose `stop_reason` is `end_turn` or `stop_sequence` SHALL end the run with an `ok` result whose message is
the text of its `text` blocks.

#### Scenario: The model is done
- **WHEN** a reply ends `end_turn` holding the text `Wrote out/hello.txt.`
- **THEN** a `turn` event for that text is followed by an `ok` result whose message is `Wrote out/hello.txt.`

### Requirement: Assistant text is reported as turns
Each reply's text, when it has any, SHALL be one `turn` event with role `assistant`, sent before the reply's
`tool_call` events. `thinking` and `redacted_thinking` blocks SHALL stay in the transcript only.

#### Scenario: Text and a tool call
- **WHEN** a reply holds the text `I'll write the file.` and then a `tool_use` for `Write`
- **THEN** a `turn` with that text comes before the `Write` call's `tool_call`

### Requirement: A reply that stops for another reason ends the run with an error
A reply whose `stop_reason` is `refusal` SHALL end the run with `error`, `reason` `refused`, holding any text and the
stop's details. `max_tokens` SHALL end it with `output-limit`, and no `tool_use` it holds SHALL be carried out.
`model_context_window_exceeded` SHALL end it with `context-length`. Any other stop reason SHALL end it with `engine`,
naming it.

#### Scenario: A refusal
- **WHEN** a reply ends with `stop_reason` `refusal`
- **THEN** the run ends with an `error` result with `reason` `refused`, saying the model refused

#### Scenario: The output limit inside a tool call
- **WHEN** a reply ends `max_tokens` holding a `tool_use` whose input was cut
- **THEN** no `tool_call` event is sent, and the run ends with `error` and `reason` `output-limit`

#### Scenario: A stop reason for server tools
- **WHEN** a reply ends with `stop_reason` `pause_turn`
- **THEN** the run ends with `error` and `reason` `engine`, naming `pause_turn`

### Requirement: Usage is summed into the result
The result SHALL carry the run's usage summed over every reply as the Messages API defines it: `inputTokens` from
`input_tokens`, `cacheReadTokens` from `cache_read_input_tokens` and `cacheWriteTokens` from
`cache_creation_input_tokens`, each cache counter only when every reply reports it, and `outputTokens`. A reply with no
usage SHALL make the result carry none, with a `log` warning.

#### Scenario: Two replies with cached input
- **WHEN** one reply reports 60 input, 40 cache-read and 10 output tokens, and a second 200 input, 0 cache-read and 20
  output tokens
- **THEN** the result's usage is `inputTokens` 260, `cacheReadTokens` 40 and `outputTokens` 30

#### Scenario: Cache writes reported by only one reply
- **WHEN** one reply reports `cache_creation_input_tokens` 50 and the other doesn't report it
- **THEN** the result has no `cacheWriteTokens`

### Requirement: Cost is estimated from troupe's price
The Messages API reports no cost, so the result SHALL NOT carry `costUsd`. When `run/start`'s runtime carries a price,
the result SHALL carry the run's summed usage at that price as `estimatedCostUsd`, worked out by the plugin SDK's
estimator, or none when the estimator gives none.

#### Scenario: Claude with a price
- **WHEN** a run's replies report 260 input, 40 cache-read and 30 output tokens, and the price is 1 dollar per million
  input tokens, 0.1 per million cache reads and 5 per million output tokens
- **THEN** the result's `estimatedCostUsd` is 0.000414, and it has no `costUsd`

#### Scenario: No price
- **WHEN** `run/start` carries no price
- **THEN** the result has neither `costUsd` nor `estimatedCostUsd`

### Requirement: A reply's model, when not the runtime's, is a served_model event
When a reply's `model` isn't empty and isn't the runtime's model, the runner SHALL send `served_model` naming it, the
first time that model answers in the run, before the reply's `turn`, tool calls or `result`.

#### Scenario: A local engine names another model
- **WHEN** the runtime's model is `gemma` and the reply's `model` is `google/gemma-4-e4b`
- **THEN** the runner sends one `served_model` with `model` `google/gemma-4-e4b` before that reply's `turn`

### Requirement: Redirects are never followed
A response that redirects SHALL NOT be followed, whatever the library would do by default. The run SHALL end with
`error`, `reason` `configuration`, naming the status and the location it pointed to.

#### Scenario: A redirect to another host
- **WHEN** the endpoint answers 307 with `Location: https://elsewhere.example/v1/messages`
- **THEN** no request reaches `elsewhere.example`, and the run ends with an `error` result naming 307 and that
  location

### Requirement: Transient failures are retried by the runner, not the library
The library's own retries SHALL be off. A request failing with a rate limit (429), a server error (500 or above,
`overloaded_error` included, in a status or in a stream's `error` event), a network error or a timeout SHALL be
retried up to the runner's named attempts, with a growing delay, each retry first reported as a `retry` event.

#### Scenario: Overloaded, then success
- **WHEN** the first request is answered 529 with `overloaded_error` and the second succeeds
- **THEN** a `retry` event with attempt 1 and reason `server` comes before the second request, and the run goes on

#### Scenario: Retries run out
- **WHEN** every attempt is answered 500 and the runner makes at most 3 attempts, the first included
- **THEN** the service receives exactly 3 requests, the runner sends 2 `retry` events, and the run ends with `error`
  and `reason` `server`, naming the status and the attempts made

#### Scenario: An error event mid-stream
- **WHEN** a reply's stream sends an `error` event with type `overloaded_error`
- **THEN** the reply is dropped, and a `retry` with reason `server` follows

### Requirement: A rate limit's Retry-After is honoured within a named cap
When a 429 or a server error carries `retry-after-ms` or `Retry-After`, the retry's delay SHALL be that value. A 429
asking a longer wait than the runner's named maximum delay SHALL end the run with `error`, `reason` `rate-limit`,
naming the wait asked for, and a server error's delay SHALL be cut to that maximum.

#### Scenario: A short wait
- **WHEN** a request is answered 429 with `Retry-After: 2`
- **THEN** the `retry` event has reason `rate-limit` and `delayMs` 2000

#### Scenario: A wait longer than the cap
- **WHEN** a request is answered 429 with `Retry-After` an hour
- **THEN** the run ends with an `error` result with `reason` `rate-limit`, naming the hour asked for and the cap

### Requirement: Failures retrying can't fix end the run at once
A failure that isn't transient SHALL NOT be retried, and SHALL end the run with an `error` result naming the status,
the error's type and the service's message, with the reason the runner's one table gives it: `authentication_error`
and `permission_error` `authentication`, `billing_error` `quota`, and a client error the table doesn't name `other`.

#### Scenario: A rejected credential
- **WHEN** the first request is answered 401 with `authentication_error`
- **THEN** no request is retried, and the run ends with `error` and `reason` `authentication`, holding the service's
  message

#### Scenario: Out of credit
- **WHEN** a request is answered 402 with `billing_error`
- **THEN** it isn't retried, and the run ends with `error` and `reason` `quota`

### Requirement: An endpoint or service that can't serve the run is a configuration failure
A request redirected, answered 404 (a model the service doesn't have, or nothing at the endpoint's path), or answered
2xx with a `Content-Type` present that isn't `text/event-stream`, SHALL end the run with `reason` `configuration`, not
retried. A 404 without the API's error shape SHALL name the URL and say the endpoint must be the API's base URL.

#### Scenario: Nothing at the endpoint's path
- **WHEN** a request is answered 404 without the Messages API's error shape
- **THEN** the run ends with `error` and `reason` `configuration`, naming the URL it was sent to

#### Scenario: A model the service doesn't have
- **WHEN** a request is answered 404 with `not_found_error` about the model
- **THEN** the run ends with `error` and `reason` `configuration`

#### Scenario: An answer that isn't a stream
- **WHEN** a request is answered 200 with `Content-Type: application/json`
- **THEN** the run ends with `error` and `reason` `configuration`, saying the runner asked for a stream

### Requirement: A broken stream is retried as a network failure
A reply's stream cut short SHALL be dropped whole, including any tool calls it had begun, and the request retried as a
network failure. A stream is cut short when it ends before `message_stop`, breaks, or sends nothing for the runner's
named stream timeout.

#### Scenario: The connection drops mid-reply
- **WHEN** a reply's stream stops halfway through a `tool_use` block's input
- **THEN** no `tool_call` event is sent for it, a `retry` with reason `network` follows, and the retried reply is used

#### Scenario: The stream goes quiet
- **WHEN** a reply's stream sends nothing for longer than the stream timeout
- **THEN** the request is abandoned and retried, with a `retry` event with reason `network`

### Requirement: A reply the runner can't read ends the run
A reply the service finished but the library or the runner can't read (an event that isn't JSON, a delta for a
content block it never started, a `tool_use` without an id or a name) SHALL end the run at once with `error` and
`reason` `engine`, naming what was wrong, not retried, and no tool call from it SHALL be carried out.

#### Scenario: An event that isn't JSON
- **WHEN** a reply's stream holds the line `data: not json` followed by a blank line
- **THEN** no `retry` event is sent, and the run ends with `error` and `reason` `engine`, saying an event in the reply
  isn't JSON

### Requirement: The runner's unexpected failure is a runner failure
An exception the runner didn't expect during a run SHALL end it with `error` and `reason` `runner`, and any failure
the runner's tables don't name with `other`, its message naming what happened.

#### Scenario: The runner fails
- **WHEN** the runner raises an exception it didn't expect during a run
- **THEN** the `result` has `reason` `runner`

### Requirement: A context-length refusal ends the run with context-length
A failure the runner's one table of context-length signals names SHALL NOT be retried, and SHALL end a run told
`fail` with `error` and `reason` `context-length`, saying the conversation is longer than the model's context. The
table SHALL hold Claude's `prompt is too long` refusal and each local engine's own signal the runner is proved against.

#### Scenario: Claude's refusal
- **WHEN** a request is answered 400 with `invalid_request_error` and the message `prompt is too long: 210000 tokens >
  200000 maximum`
- **THEN** it isn't retried, and the run ends with `error` and `reason` `context-length`

#### Scenario: LM Studio's refusal
- **WHEN** a reply's stream holds an `error` event with `api_error` and the message `The number of tokens to keep from
  the initial prompt is greater than the context length`
- **THEN** it isn't retried as a server error, and the run ends with `error` and `reason` `context-length`

### Requirement: A reply made from a cut conversation is never acted on
The conversation only grows, so a reply whose reported prompt (its input, cache-read and cache-write tokens) is
smaller than the previous request's SHALL be taken as made from a conversation the engine cut. No `turn` or tool call
from it SHALL be sent, and a run told `fail` SHALL end with `error` and `reason` `context-length`.

#### Scenario: An engine that cuts the middle
- **WHEN** a run's second request is reported as 5,900 prompt tokens and its third, which adds a tool result to it, as
  4,058
- **THEN** no `turn` or `tool_call` event is sent for the third reply, and the run ends with `error` and `reason`
  `context-length`, saying the engine answered from less of the conversation than it was sent

#### Scenario: A conversation that grows
- **WHEN** each reply reports a larger prompt than the one before
- **THEN** the run goes on

### Requirement: A run stops before the context window the person named
When `contextWindow` is set, a reply whose reported prompt and output reach it SHALL be acted on, and the runner SHALL
send no further request in a run told `fail`, ending it with `error` and `reason` `context-length`, naming the
window. A reply whose reported prompt alone reaches it SHALL NOT be acted on.

#### Scenario: The window is reached
- **WHEN** a run with `contextWindow` 8192 gets a reply asking for a tool call, reported as 7,900 prompt tokens and 300
  output tokens
- **THEN** the call is carried out, no further request is sent, and the run ends with `error` and `reason`
  `context-length`

#### Scenario: No window named
- **WHEN** a run's options don't set `contextWindow`
- **THEN** only the engine's refusals and a shrinking prompt end the run for its context

### Requirement: A run told compact compacts its conversation and asks again
When a run told `compact` meets a context-length signal, a shrinking prompt or its `contextWindow`, the runner SHALL
replace old `tool_result` contents with the SDK's stub, oldest first, until its estimate is at or below a named share
of the last whole request's prompt, then send a `context` event and the request again, not counted as a turn.

#### Scenario: A refused request, then success
- **WHEN** a run told `compact` has its third request refused as too long
- **THEN** the runner sends a `context` event with `kind` `truncated` and `by` `runner`, then sends the third request
  again with the oldest results stubbed, and the run's turn count and usage are unchanged by the refusal

#### Scenario: What is never removed
- **WHEN** a run told `compact` compacts its conversation
- **THEN** the `system`, the first user message, every assistant message (its `thinking` and `tool_use` blocks
  included) and the latest turn's `tool_result`s are sent unchanged

#### Scenario: Nothing left to remove
- **WHEN** a run told `compact` meets a context-length signal and its only results are the latest turn's
- **THEN** no `context` event is sent, and the run ends with `error` and `reason` `context-length`, saying compaction
  found nothing more to remove

### Requirement: The transcript is what the library exposes
The runner SHALL send as transcript records, in order and before the events they lead to: each request's parameters
as passed to the library (`sent`); each stream event and error body as the library gives them, serialised
(`received`); and each response's status with the headers named in one place, and each stream it abandons (`note`).

#### Scenario: A run's transcript
- **WHEN** a run makes one request and gets one streamed reply
- **THEN** its transcript holds a `sent` record of the request's parameters, a `note` of the status, then one
  `received` record per stream event, in order

#### Scenario: No request header
- **WHEN** any transcript record is read
- **THEN** none holds a request header

#### Scenario: troupe offers no kinds
- **WHEN** `initialize` offers no capabilities
- **THEN** the runner answers with none, and sends the same records with no kind

### Requirement: The library's own logging stays out of the run's output
The runner SHALL keep the library's loggers off standard output, pass only their warnings and above to standard error,
cut to fit, and turn off the library's OpenTelemetry tracing, whatever `ANTHROPIC_LOG` says.

#### Scenario: Debug logging asked for
- **WHEN** the runner's environment holds `ANTHROPIC_LOG=debug`
- **THEN** standard output holds only protocol messages, and standard error holds no request header

### Requirement: Every timeout the library applies is one of the runner's named settings
Every timeout the library applies (connect, read, write and pool) SHALL be set from the runner's named settings, never
left to the library's default, and the runner's README SHALL name each setting and its default.

#### Scenario: A held connection
- **WHEN** the fake endpoint accepts a request and sends nothing
- **THEN** the runner abandons it after its named stream timeout, not the library's ten-minute default

### Requirement: Summaries fit below the event limit
Each `turn` text, `inputSummary`, `outputSummary` and result or log message SHALL be cut, on a UTF-8 boundary, so that
the event serialises within `limits.eventMaxBytes` and the runner's summary limit, ending by saying how many bytes were
left out.

#### Scenario: A long final reply
- **WHEN** the final reply's text is 1 MiB and `eventMaxBytes` is 65536
- **THEN** the `turn` and `result` events each serialise within 65536 bytes, and each ends by naming the bytes left out

### Requirement: Cancel and end of input stop the request in flight
On `run/cancel`, or when its standard input closes, the runner SHALL abandon the library's request in flight, carry out
no further tool call, send no further request, and exit within troupe's cancel grace period, whatever the library's
timeouts are. After a cancel it SHALL send no `result`.

#### Scenario: Cancel during a held reply
- **WHEN** the host cancels a run while the fake endpoint holds a reply's stream open
- **THEN** the runner acknowledges the cancel, the endpoint sees its connection closed, and the runner exits within the
  grace without a `result`

#### Scenario: A stop between tool calls
- **WHEN** the run is stopped after the first of a reply's two tool calls is carried out
- **THEN** the second isn't carried out, and no further request is sent

### Requirement: The runner publishes its schemas
The runner SHALL publish its options schema and its error codes' schema, each passing the protocol's strictness
check. Its error codes SHALL include `anthropic.unknown-option`, `anthropic.invalid-options`, `anthropic.no-runtime`,
`anthropic.unsupported-endpoint`, `anthropic.insecure-endpoint`, `anthropic.credential-mismatch` and
`anthropic.malformed-credential`.

#### Scenario: The schemas pass the strictness check
- **WHEN** the protocol's strictness check runs over the runner's published schemas
- **THEN** both pass, and each documented option validates against the options schema

### Requirement: The runner conforms to the contract
The runner, pointed at a fake Messages endpoint, SHALL pass troupe's runner conformance suite.

#### Scenario: The conformance suite
- **WHEN** the conformance suite runs against the runner with a runtime naming the fake endpoint
- **THEN** every check passes

### Requirement: Fixtures pair service output with protocol events
Each fixture SHALL hold a service's replies for one run, its provenance, and the run events and outcome they map to,
recorded from a real service where it can be made to give them, else derived or built from the documented shape, and
saying which. A test SHALL replay each fixture through the fake endpoint.

#### Scenario: Replaying a fixture
- **WHEN** a fixture's recorded replies are replayed through the fake endpoint
- **THEN** the runner sends exactly the fixture's expected events, and the host derives its expected outcome

#### Scenario: The fixtures there are
- **WHEN** the fixtures are listed
- **THEN** there is at least a tool loop that succeeds against LM Studio and one against Claude's API, a context
  refusal from each, a conversation LM Studio cut, a rejected credential, a rate limit, an overload, a broken stream,
  the output limit and a refusal, each naming its service and whether it was recorded, derived or built

### Requirement: Fixtures hold no secrets
No committed fixture SHALL contain a credential, an account or organisation id, or a host path outside the fixture.

#### Scenario: A secret in a fixture
- **WHEN** a fixture contains a string matching a credential pattern or the capturing host's home path
- **THEN** the fixture test fails, naming the fixture and the line

### Requirement: Fixtures that need a working credential are captured by the owner
The capture tool SHALL capture every fixture it can without a working credential, against a local engine or against
Claude's API with a deliberately invalid key. A fixture that needs a working credential SHALL be captured by the owner
running the tool, which reads the key from the environment and never writes it.

#### Scenario: A rejected credential fixture
- **WHEN** the capture tool captures the rejected-credential fixture
- **THEN** it sends a deliberately invalid key, and the fixture's provenance says no working credential was used

### Requirement: Live tests run a real service only when asked
Opt-in tests SHALL run the runner against a real service: Claude's API only when `TROUPE_LIVE_ANTHROPIC` is `1`, and
a local engine only when `TROUPE_LIVE_ANTHROPIC_LOCAL` is `1`, never in CI, each with a model pinned in one place and
a small token budget and turn limit, naming the endpoint and model it used.

#### Scenario: Not asked
- **WHEN** the test suite runs without either variable
- **THEN** both live tests are skipped, each saying how to run it

#### Scenario: A live run
- **WHEN** the owner runs one with its variable set and a runtime that reaches its service
- **THEN** a run that writes and reads back a file ends `succeeded` within its token budget, and the file holds what
  was asked
