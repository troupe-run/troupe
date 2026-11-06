# openai-runner Specification

## Purpose
Capability: `cap:actor-runners`

The OpenAI runner: an actor runner that drives OpenAI's Responses API, or any service that serves it, with troupe's
own tool loop, so the runner contract is tested by a hosted engine that needs a credential, costs money and fails in
a hosted service's ways.

## Requirements

### Requirement: The OpenAI runner is a self-contained plugin
The runner SHALL live in `plugins/runner-openai` with its own package, tests and published schemas, and SHALL import
nothing of troupe's except the plugin SDK. It SHALL identify itself as `openai` in its handshake and its `init`
event.

#### Scenario: Only the SDK is imported
- **WHEN** the import contracts are checked
- **THEN** no module of the runner imports `troupe` or any package of troupe's other than `troupe_plugin_sdk`

#### Scenario: Its name
- **WHEN** the runner answers `initialize`
- **THEN** its name is `openai` and its version is the package's version

### Requirement: The runner speaks the Responses API
The runner SHALL send each request as `POST` to the runtime's endpoint followed by `/responses`, streamed, and SHALL
use no other API. Its `init` event's `engine.name` SHALL be `responses`.

#### Scenario: Where a request goes
- **WHEN** a run's runtime has the endpoint `https://api.openai.com/v1`
- **THEN** each request goes to `https://api.openai.com/v1/responses`, with `stream` true

#### Scenario: Init names the API
- **WHEN** a run starts
- **THEN** its `init` event's `engine.name` is `responses`

### Requirement: The service comes from the run's runtime
The runner SHALL take the endpoint, the model and the credential from the runtime troupe resolves for the run (spec:
runtimes, #278), and from nowhere else. Its options SHALL hold no endpoint, model or credential, and no endpoint or
model SHALL be hard-coded in the runner.

#### Scenario: An endpoint in the options
- **WHEN** a `run/start`'s options hold `endpoint`
- **THEN** `run/start` is refused with `openai.unknown-option`, naming `endpoint`

#### Scenario: A run without a runtime
- **WHEN** a `run/start` carries no runtime
- **THEN** `run/start` is refused with `openai.no-runtime`, whose fix says to name a runtime for the actor

#### Scenario: The runtime's model is asked for
- **WHEN** a run's runtime names the model `small-model`
- **THEN** every request the runner sends asks for `small-model`, and the `init` event's `engine.model` is
  `small-model`

### Requirement: The credential is read from TROUPE_RUNTIME_CREDENTIAL
The runner SHALL read the run's credential only from `TROUPE_RUNTIME_CREDENTIAL`, and only when `run/start`'s
`runtime.credential` is `true`. When the two disagree, it SHALL refuse `run/start` with `openai.credential-mismatch`,
saying which way without the value, and send nothing. A credential holding whitespace or a control character SHALL be
refused with `openai.malformed-credential`, naming the variable and never the value.

#### Scenario: A credential run start promises and the environment lacks
- **WHEN** `runtime.credential` is `true` and `TROUPE_RUNTIME_CREDENTIAL` isn't set
- **THEN** `run/start` is refused with `openai.credential-mismatch`, and no request is sent

#### Scenario: A credential run start doesn't mention
- **WHEN** `runtime.credential` is `false` and `TROUPE_RUNTIME_CREDENTIAL` holds a value
- **THEN** `run/start` is refused with `openai.credential-mismatch`, and the error holds no part of the value

#### Scenario: A key read with its line ending
- **WHEN** `TROUPE_RUNTIME_CREDENTIAL` holds a key followed by `\r\n`
- **THEN** `run/start` is refused with `openai.malformed-credential`, the error holds no part of the key, and no
  request is sent

### Requirement: The runner's options are closed
`run/start` options SHALL be an object with only `maxTurns` (a positive integer) and `maxTotalTokens` (a positive
integer), each optional. An option the runner doesn't define, or a value of the wrong shape, SHALL be refused with an
error naming it, and no request SHALL be sent.

#### Scenario: An unknown option
- **WHEN** the options hold `troupeConformanceUnknownOption`
- **THEN** `run/start` is refused with `openai.unknown-option`, whose `details.where` names the option

#### Scenario: A malformed value
- **WHEN** `maxTurns` is `0` or `maxTotalTokens` is `"lots"`
- **THEN** `run/start` is refused with `openai.invalid-options`, whose `details.where` names the option and whose fix
  names what is valid

### Requirement: Every run has a turn limit and a token budget
The runner SHALL always limit a run to `maxTurns` requests, a retried request counting once, and SHALL send no request
once the run has used `maxTotalTokens` tokens, the sum of every response's reported input and output tokens. Each
response is counted whole after it arrives, so a run can end above its budget. Each limit SHALL default, when the
options don't set it, to a named setting in one place in the runner.

#### Scenario: The turn limit is reached
- **WHEN** a run with `maxTurns` 3 gets a tool call in each of its first three responses
- **THEN** the runner carries out the third response's calls, sends no fourth request, and ends with an `error`
  result saying the turn limit of 3 was reached

#### Scenario: The token budget is spent
- **WHEN** a run with `maxTotalTokens` 1000 has used 1200 tokens after a response that asks for a tool call
- **THEN** the runner carries out that call, sends no further request, and ends with an `error` result saying the
  token budget of 1000 was spent, with the tokens used

#### Scenario: No limits in the options
- **WHEN** a run starts with empty options
- **THEN** its turn limit and token budget are the runner's named defaults

#### Scenario: A last reply past the budget
- **WHEN** a run with `maxTotalTokens` 1000 gets a reply without a tool call that brings its usage to 1200
- **THEN** the run ends with an `ok` result reporting the 1200 tokens

### Requirement: The character is the instructions and the direction the first input
The first request SHALL carry `instructions` made of the runner's fixed instructions followed by the actor's character
when it has one, and an `input` holding one user message with the direction unchanged.

#### Scenario: An actor with a character
- **WHEN** a run starts with the character `You are terse.` and the direction `Write out/hello.txt`
- **THEN** the first request's `instructions` end with `You are terse.`, and its `input` is one user message whose
  content is `Write out/hello.txt`

#### Scenario: An actor without a character
- **WHEN** a run starts with no character
- **THEN** the `instructions` hold only the runner's fixed instructions

### Requirement: The service is never asked to keep the conversation
Every request SHALL set `store` to `false` and SHALL NOT name a previous response, so the service keeps nothing of the
run and each request carries the whole conversation. Each SHALL ask for reasoning items' encrypted content, so a
reasoning model's earlier reasoning can be sent back.

#### Scenario: A request's storage
- **WHEN** any request is sent
- **THEN** its `store` is `false`, it has no `previous_response_id`, and its `include` holds
  `reasoning.encrypted_content`

### Requirement: The model is offered the SDK's tools
Each request SHALL offer the model the plugin SDK's tool definitions as Responses function tools, each with its name,
description and input schema unchanged and `strict` false, and the `init` event SHALL list the same tools.

#### Scenario: The tools offered
- **WHEN** the first request is sent
- **THEN** its `tools` are the SDK's seven tools, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Delete` and `Move`, in
  that order, each of type `function` with its `name`, `description`, `parameters` and `strict` false

### Requirement: The runner applies the effects by checking each call
The runner SHALL carry out each tool call the model asks for through the plugin SDK, which checks it against the
actor's declared effects first. Its `init` event's `effects` SHALL be `checked`.

#### Scenario: A write the actor didn't declare
- **WHEN** a read-only actor's model asks to `Write` `out/hello.txt`
- **THEN** the file isn't written, the `tool_result` is an error naming the `write` effect, and the model is sent
  that result

#### Scenario: Init
- **WHEN** a run starts
- **THEN** its `init` event's `effects` is `checked`

### Requirement: Tool calls are carried out in order and answered in the next request
When a response's output holds `function_call` items, the runner SHALL carry them out one at a time in the order the
output gives, and send each call's `tool_call` and `tool_result` events. The next request's `input` SHALL be the
previous request's `input`, then the response's output items unchanged, then one `function_call_output` per call
holding its `call_id` and output.

#### Scenario: Two calls in one response
- **WHEN** a response's output holds a call to `Read` `a.txt` and then one to `Read` `b.txt`
- **THEN** the events are the `tool_call` and `tool_result` for `a.txt`, then those for `b.txt`, and the next
  request's `input` ends with two `function_call_output` items in that order, each naming its call's `call_id`

#### Scenario: Reasoning is sent back as the service gave it
- **WHEN** a response's output holds a `reasoning` item and then a `function_call`
- **THEN** the next request's `input` holds that `reasoning` item, unchanged, before the `function_call`

#### Scenario: A call without a call id
- **WHEN** a response's output holds a `function_call` with no `call_id`
- **THEN** the run ends with an `error` result saying the service sent a tool call it can't be answered for, naming
  the call's tool

### Requirement: A malformed tool call is answered, not fatal
A tool call whose arguments aren't a JSON object, or whose tool isn't one of the SDK's, SHALL be answered with an
error result the model is sent, as the SDK makes it, and the run SHALL go on.

#### Scenario: Arguments that aren't JSON
- **WHEN** a response asks to `Write` with arguments `{"file_path": "a.txt"`
- **THEN** the `tool_result` is an error saying the arguments aren't a JSON object, and the next request carries it

### Requirement: A completed reply without tool calls ends the run
A response with status `completed` and no `function_call` in its output SHALL end the run with an `ok` result whose
message is the text of its output messages.

#### Scenario: The model is done
- **WHEN** a response completes with a message whose text is `Wrote out/hello.txt.` and no function call
- **THEN** a `turn` event for that text is followed by an `ok` result whose message is `Wrote out/hello.txt.`

### Requirement: Assistant text is reported as turns
Each response's output text, when it has any, SHALL be one `turn` event with role `assistant`, sent before the
`tool_call` events of the same response. Reasoning SHALL stay in the transcript only.

#### Scenario: Text and a tool call
- **WHEN** a response's output holds a message `I'll write the file.` and then a call to `Write`
- **THEN** a `turn` with that text comes before the `Write` call's `tool_call`

### Requirement: A refusal ends the run with an error
A response whose output holds a refusal SHALL end the run with an `error` result saying the model refused, holding the
refusal's text. It SHALL NOT be retried.

#### Scenario: A refusal
- **WHEN** a response's output message holds the refusal `I can't help with that.`
- **THEN** the run ends with an `error` result whose message says the model refused and holds `I can't help with
  that.`

### Requirement: An incomplete response ends the run with an error
A response with status `incomplete` SHALL end the run with an `error` result naming its reason: the output limit for
`max_output_tokens`, the service's content filter for `content_filter`, and the reason as given otherwise. A status
the runner doesn't know SHALL end the run with an `error` result naming it.

#### Scenario: The output limit
- **WHEN** a response ends `incomplete` with reason `max_output_tokens`
- **THEN** the run ends with an `error` result saying the response reached the service's output limit

#### Scenario: A content filter
- **WHEN** a response ends `incomplete` with reason `content_filter`
- **THEN** the run ends with an `error` result saying the service's content filter stopped the response

#### Scenario: An unknown status
- **WHEN** a response ends with status `paused`
- **THEN** the run ends with an `error` result naming `paused`

### Requirement: A failed response is retried only when the service's side failed
A response that ends `failed`, or a stream's `error` event, SHALL be retried as a server failure when its error code
is one the runner names in one place as the service's own, and otherwise SHALL end the run with an `error` result
naming the code and the service's message.

#### Scenario: A server error mid-stream
- **WHEN** a response ends `failed` with the code `server_error`
- **THEN** a `retry` event with reason `server` follows, and the request is sent again

#### Scenario: A failure retrying can't fix
- **WHEN** a response ends `failed` with the code `invalid_prompt`
- **THEN** it isn't retried, and the run ends with an `error` result naming `invalid_prompt` and the service's message

### Requirement: Usage is summed into the result
The result SHALL carry the run's usage summed over every response: `cacheReadTokens` as the input tokens read from the
service's cache, `cacheWriteTokens` as those written to it where the service reports them, `inputTokens` as the input
tokens less both, and `outputTokens`. When a response reports no usage, the result SHALL carry no usage and the runner
SHALL say so in a `log` warning.

#### Scenario: Two responses with cached input
- **WHEN** one response reports 100 input tokens, 40 of them cached, and 10 output tokens, and a second reports 200
  input tokens, none cached, and 20 output tokens
- **THEN** the result's usage is `inputTokens` 260, `cacheReadTokens` 40 and `outputTokens` 30

#### Scenario: Tokens written to the cache
- **WHEN** a response reports 300 input tokens, 100 of them cached and 50 written to the cache, and 10 output tokens
- **THEN** the result's usage is `inputTokens` 150, `cacheReadTokens` 100, `cacheWriteTokens` 50 and
  `outputTokens` 10

#### Scenario: A service that reports no usage
- **WHEN** a response completes without usage
- **THEN** a `log` warning says the service reported no usage, so only the turn limit bounds the run, and the result
  has no `usage`

### Requirement: Cost is reported only as the service reports it
The result's `costUsd` SHALL be the sum of the costs the service reports in its responses' usage, and SHALL be absent
when any response reports none. The runner SHALL NOT estimate a cost.

#### Scenario: A service that reports no cost
- **WHEN** every response's usage has token counts and no cost
- **THEN** the result has no `costUsd`

#### Scenario: A service that reports a cost
- **WHEN** two responses' usage report costs of 0.001 and 0.002
- **THEN** the result's `costUsd` is 0.003

### Requirement: The credential goes only in the Authorization header
When the runtime has a credential, the runner SHALL send it as `Authorization: Bearer <credential>` on each request to
the runtime's endpoint, and nowhere else. It SHALL NOT appear in any run event, transcript record, log, error or
standard error output.

#### Scenario: A known credential is nowhere troupe can see
- **WHEN** a run with the credential `sk-canary-0123456789` ends in each way the fake endpoint can make it end
- **THEN** the fake endpoint received it in each request's `Authorization` header, and no event, transcript record,
  error or standard error line holds `sk-canary-0123456789`

#### Scenario: A runtime without a credential
- **WHEN** a run's runtime has no credential
- **THEN** its requests carry no `Authorization` header

### Requirement: A service's echo of the credential is masked
Where a service's response repeats the credential, whole or with part of it masked, the runner SHALL replace it with
`[credential]` in everything it sends troupe, the transcript included, before sending it.

#### Scenario: A 401 that quotes part of the key
- **WHEN** the run's credential is `sk-canary-0123456789` and a 401's message reads `Incorrect API key provided:
  sk-cana*********6789`
- **THEN** the result's message and the transcript's record of that body read `Incorrect API key provided:
  [credential]`

### Requirement: A credential never travels in the clear
The runner SHALL refuse a `run/start` whose runtime has a credential and an `http` endpoint whose host isn't a
loopback address, with `openai.insecure-endpoint` naming the endpoint, and send nothing.

#### Scenario: Plain HTTP to another host
- **WHEN** a run's runtime has a credential and the endpoint `http://models.example.com/v1`
- **THEN** `run/start` is refused with `openai.insecure-endpoint`, and no request is sent

#### Scenario: Plain HTTP to this machine
- **WHEN** a run's runtime has a credential and the endpoint `http://127.0.0.1:11434/v1`
- **THEN** the run starts and its requests go to that endpoint

### Requirement: Redirects are never followed
A response that redirects SHALL NOT be followed. The run SHALL end with an `error` result naming the status and the
location it pointed to, so neither the credential nor the conversation is sent anywhere the runtime didn't name.

#### Scenario: A redirect to another host
- **WHEN** the endpoint answers 307 with `Location: https://elsewhere.example/v1/responses`
- **THEN** no request reaches `elsewhere.example`, and the run ends with an `error` result naming 307 and that
  location

### Requirement: Transient failures are retried and reported
A request that fails with a rate limit (429), a server error (500 or above), a network error or a timeout SHALL be
retried up to the runner's named maximum attempts, with a growing delay, each retry reported first as a `retry` event
with reason `rate-limit`, `server` or `network`. A server error's `Retry-After` SHALL set its delay, up to the runner's
named maximum delay. When the attempts run out, the run SHALL end with an `error` result.

#### Scenario: A server error, then success
- **WHEN** the first request is answered 503 and the second succeeds
- **THEN** a `retry` event with attempt 1, reason `server` and the delay comes before the second request, and the run
  goes on

#### Scenario: Retries run out
- **WHEN** every attempt is answered 500
- **THEN** after the last attempt the run ends with an `error` result naming the status and the attempts made

#### Scenario: A server error asking a long wait
- **WHEN** a request is answered 503 with `Retry-After: 120`
- **THEN** the `retry` event has reason `server` and the runner's maximum delay, and the request is sent again

### Requirement: A rate limit's Retry-After is honoured within a named cap
When a 429 response carries `Retry-After`, the retry's delay SHALL be that value. When it is longer than the runner's
named maximum delay, the run SHALL end with an `error` result naming the wait asked for, rather than waiting it out.

#### Scenario: A short wait
- **WHEN** a request is answered 429 with `Retry-After: 2`
- **THEN** the `retry` event has reason `rate-limit` and `delayMs` 2000

#### Scenario: A wait longer than the cap
- **WHEN** a request is answered 429 with `Retry-After` an hour
- **THEN** the run ends with an `error` result naming the hour asked for and the cap

### Requirement: Failures retrying can't fix end the run at once
An authentication failure (401 or 403), a quota error, a context-length error and any other client error SHALL NOT be
retried. The run SHALL end with an `error` result naming the status and the service's own message.

#### Scenario: A rejected credential
- **WHEN** the first request is answered 401 with the message `Incorrect API key provided`
- **THEN** no request is retried, and the run ends with an `error` result saying the service refused the credential,
  holding `Incorrect API key provided`

#### Scenario: Out of quota
- **WHEN** a request is answered 429 with the error code `insufficient_quota`
- **THEN** it isn't retried, and the run ends with an `error` result saying the account is out of quota

#### Scenario: Nothing at the endpoint's path
- **WHEN** a request is answered 404 without OpenAI's error shape
- **THEN** the run ends with an `error` result naming the URL it was sent to, and saying the runtime's endpoint must
  be the base URL its Responses API is served under, often ending in `/v1`

#### Scenario: The context is too long
- **WHEN** a request is answered 400 with the error code `context_length_exceeded`
- **THEN** it isn't retried, and the run ends with an `error` result saying the conversation is longer than the
  model's context

### Requirement: A broken stream is retried as a network failure
A response stream that ends before a final event (`response.completed`, `response.incomplete` or `response.failed`),
holds a line that isn't a valid event, or goes silent for the runner's named stream timeout SHALL be dropped whole,
including any tool calls it had begun, and the request retried as a network failure.

#### Scenario: The connection drops mid-response
- **WHEN** a response's stream stops after half a tool call's arguments
- **THEN** no `tool_call` event is sent for it, a `retry` with reason `network` follows, and the retried response is
  used instead

#### Scenario: The stream goes quiet
- **WHEN** a response sends nothing for longer than the stream timeout
- **THEN** the request is abandoned and retried, with a `retry` event with reason `network`

### Requirement: The transcript is the exchange with the service
The runner SHALL send, as `run/transcript` records in the order they happen, each request body as sent, each line of
each response's stream unchanged, its `event:` lines included, and each error response's body, each in a record that
says which it is. Request and response headers SHALL NOT be recorded, except the response headers the runner names in
one place.

#### Scenario: A run's transcript
- **WHEN** a run makes one request and gets one streamed response
- **THEN** its transcript holds a record of the request body, then one record for each line of the response's
  stream, in order

#### Scenario: No request header
- **WHEN** any transcript record is read
- **THEN** none holds a request header

### Requirement: Summaries fit below the event limit
Each `turn` text, `inputSummary`, `outputSummary` and result or log message SHALL be cut, on a UTF-8 boundary, so that
the event serialises within `limits.eventMaxBytes` and the runner's summary limit. A cut summary SHALL end by saying
how many bytes were left out.

#### Scenario: A long final reply
- **WHEN** the final response's text is 1 MiB and `eventMaxBytes` is 65536
- **THEN** the `turn` and `result` events each serialise within 65536 bytes, and each ends by naming the bytes left
  out

### Requirement: Cancel and end of input stop the request in flight
On `run/cancel`, or when its standard input closes, the runner SHALL abandon any request in flight, carry out no further
tool call, send no further request, and exit within troupe's cancel grace period. After a cancel it SHALL send no
`result`.

#### Scenario: Cancel during a slow response
- **WHEN** the host cancels a run while the fake endpoint is holding a response open
- **THEN** the runner acknowledges the cancel, the endpoint sees its connection closed, and the runner exits without
  a `result`

#### Scenario: A stop between tool calls
- **WHEN** the run is stopped after the first of a response's two tool calls is carried out
- **THEN** the second isn't carried out, and no further request is sent

### Requirement: The runner publishes its schemas
The runner SHALL publish its options schema and its error codes' schema, each passing the protocol's strictness
check. Its error codes SHALL include `openai.unknown-option`, `openai.invalid-options`, `openai.no-runtime`,
`openai.insecure-endpoint` and `openai.credential-mismatch`.

#### Scenario: The schemas pass the strictness check
- **WHEN** the protocol's strictness check runs over the runner's published schemas
- **THEN** both pass, and each documented option validates against the options schema

### Requirement: The runner conforms to the contract
The runner, pointed at a fake endpoint, SHALL pass troupe's runner conformance suite.

#### Scenario: The conformance suite
- **WHEN** the conformance suite runs against the runner with a runtime naming the fake endpoint
- **THEN** every check passes

### Requirement: Fixtures pair service output with protocol events
Each fixture SHALL hold a service's responses for one run, its provenance, and the run events and outcome they map
to. Responses SHALL be recorded from a real service where it can be made to give them, and otherwise derived from a
recorded one or built from the service's documented shape, and the provenance SHALL say which. A test SHALL replay
each fixture through the fake endpoint.

#### Scenario: Replaying a fixture
- **WHEN** a fixture's recorded responses are replayed through the fake endpoint
- **THEN** the runner sends exactly the fixture's expected events, and the host derives its expected outcome

#### Scenario: The fixtures there are
- **WHEN** the fixtures are listed
- **THEN** there is at least a run with tool calls that succeeds against OpenAI and one against local Ollama, a
  rejected credential, a rate limit, a server error, a broken stream, an incomplete response and a refusal, and each
  names its service and whether it was recorded, derived or built

#### Scenario: A fixture built from documentation
- **WHEN** a fixture's responses weren't recorded
- **THEN** its provenance names what it was derived from, or the documentation page its shape was built from

### Requirement: Fixtures hold no secrets
No committed fixture SHALL contain a credential, an account or organisation id, or a host path outside the fixture.

#### Scenario: A secret in a fixture
- **WHEN** a fixture contains a string matching a credential pattern or the capturing host's home path
- **THEN** the fixture test fails, naming the fixture and the line

### Requirement: Failure fixtures are captured without a real credential
The capture tool SHALL capture every fixture it can without a working credential: against a local server that serves
the Responses API, or against the real service with a deliberately invalid key. Only a fixture that needs a working
credential SHALL use one, and the owner captures it.

#### Scenario: A rejected credential fixture
- **WHEN** the capture tool captures the rejected-credential fixture
- **THEN** it sends a deliberately invalid key, and the fixture's provenance says no working credential was used

### Requirement: A live test runs a real service only when asked
An opt-in test SHALL run the runner against a real service. It SHALL run only when `TROUPE_LIVE_OPENAI` is `1`,
never in CI, with a model pinned in one place and a small token budget and turn limit. It SHALL name the endpoint and
model it used.

#### Scenario: Not asked
- **WHEN** the test suite runs without `TROUPE_LIVE_OPENAI`
- **THEN** the live test is skipped, saying how to run it

#### Scenario: A live run
- **WHEN** the owner runs it with `TROUPE_LIVE_OPENAI=1` and a runtime with a working credential
- **THEN** a run that writes and reads back a file ends `succeeded` within its token budget, and the file holds what
  was asked
