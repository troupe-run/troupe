## Purpose

Capability: `cap:actor-runners`

The OpenAI-style runner: an actor runner that drives any service speaking the OpenAI-style Chat Completions API with
troupe's own tool loop, so the runner contract is tested by a hosted engine that needs a credential, costs money and
fails in a hosted service's ways.

## ADDED Requirements

### Requirement: The OpenAI-style runner is a self-contained plugin
The runner SHALL live in `plugins/runner-openai-chat` with its own package, tests and published schemas, and SHALL
import nothing of troupe's except the plugin SDK. It SHALL identify itself as `openai-chat` in its handshake and its
`init` event.

#### Scenario: Only the SDK is imported
- **WHEN** the import contracts are checked
- **THEN** no module of the runner imports `troupe` or any package of troupe's other than `troupe_plugin_sdk`

#### Scenario: Its name
- **WHEN** the runner answers `initialize`
- **THEN** its name is `openai-chat` and its version is the package's version

### Requirement: The service comes from the run's runtime
The runner SHALL take the endpoint, the model and the credential from the runtime troupe resolves for the run (spec:
runtimes, #278), and from nowhere else. Its options SHALL hold no endpoint, model or credential, and no endpoint or
model SHALL be hard-coded in the runner.

#### Scenario: An endpoint in the options
- **WHEN** a `run/start`'s options hold `endpoint`
- **THEN** `run/start` is refused with `openai-chat.unknown-option`, naming `endpoint`

#### Scenario: A run without a runtime
- **WHEN** a `run/start` carries no runtime
- **THEN** `run/start` is refused with `openai-chat.no-runtime`, whose fix says to name a runtime for the actor

#### Scenario: The runtime's model is asked for
- **WHEN** a run's runtime names the model `small-model`
- **THEN** every request the runner sends asks for `small-model`, and the `init` event's `engine.model` is
  `small-model`

### Requirement: The runner's options are closed
`run/start` options SHALL be an object with only `maxTurns` (a positive integer) and `maxTotalTokens` (a positive
integer), each optional. An option the runner doesn't define, or a value of the wrong shape, SHALL be refused with an
error naming it, and no request SHALL be sent.

#### Scenario: An unknown option
- **WHEN** the options hold `troupeConformanceUnknownOption`
- **THEN** `run/start` is refused with `openai-chat.unknown-option`, whose `details.where` names the option

#### Scenario: A malformed value
- **WHEN** `maxTurns` is `0` or `maxTotalTokens` is `"lots"`
- **THEN** `run/start` is refused with `openai-chat.invalid-options`, whose `details.where` names the option and
  whose fix names what is valid

### Requirement: Every run has a turn limit and a token budget
The runner SHALL always limit a run to `maxTurns` requests and to `maxTotalTokens` tokens, the sum of every
response's reported input and output tokens. Each SHALL default, when the options don't set it, to a named setting
in one place in the runner.

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

### Requirement: The direction and character become the conversation's first messages
The first request SHALL hold a system message, made of the runner's fixed instructions followed by the actor's
character when it has one, and then one user message holding the direction unchanged.

#### Scenario: An actor with a character
- **WHEN** a run starts with the character `You are terse.` and the direction `Write out/hello.txt`
- **THEN** the first request's messages are a system message ending with `You are terse.` and a user message whose
  content is `Write out/hello.txt`

#### Scenario: An actor without a character
- **WHEN** a run starts with no character
- **THEN** the system message holds only the runner's fixed instructions

### Requirement: The model is offered the SDK's tools
Each request SHALL offer the model the plugin SDK's tool definitions as Chat Completions function tools, each with
its name, description and input schema unchanged, and the `init` event SHALL list the same tools.

#### Scenario: The tools offered
- **WHEN** the first request is sent
- **THEN** its `tools` are the SDK's seven tools, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Delete` and `Move`, in
  that order, each of type `function`

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
When a response asks for tool calls, the runner SHALL carry them out one at a time in the order the response gives,
send each call's `tool_call` and `tool_result` events, and send the next request with the assistant's message and one
tool message per call, holding that call's output.

#### Scenario: Two calls in one response
- **WHEN** a response asks to `Read` `a.txt` and then `Read` `b.txt`
- **THEN** the events are the `tool_call` and `tool_result` for `a.txt`, then those for `b.txt`, and the next request
  ends with two tool messages in that order, each naming its call's id

#### Scenario: A call without an id
- **WHEN** a response asks for a tool call with no id
- **THEN** the runner gives it an id of its own, unique in the run, and uses it both in the events and in the tool
  message

### Requirement: A malformed tool call is answered, not fatal
A tool call whose arguments aren't a JSON object, or whose tool isn't one of the SDK's, SHALL be answered with an
error result the model is sent, as the SDK makes it, and the run SHALL go on.

#### Scenario: Arguments that aren't JSON
- **WHEN** a response asks to `Write` with arguments `{"file_path": "a.txt"`
- **THEN** the `tool_result` is an error saying the arguments aren't a JSON object, and the next request carries it

### Requirement: A reply without tool calls ends the run
A response that finishes with `stop` and asks for no tool call SHALL end the run with an `ok` result whose message is
the response's text.

#### Scenario: The model is done
- **WHEN** a response finishes with `stop`, has the text `Wrote out/hello.txt.` and asks for no tool call
- **THEN** a `turn` event for that text is followed by an `ok` result whose message is `Wrote out/hello.txt.`

### Requirement: Assistant text is reported as turns
Each response's text, when it has any, SHALL be one `turn` event with role `assistant`, sent before the `tool_call`
events of the same response. Text the model reports as reasoning SHALL stay in the transcript only.

#### Scenario: Text and a tool call
- **WHEN** a response has the text `I'll write the file.` and asks to `Write`
- **THEN** a `turn` with that text comes before the `Write` call's `tool_call`

### Requirement: A refusal ends the run with an error
A response carrying a refusal, or finishing with `content_filter`, SHALL end the run with an `error` result saying the
model or the service refused, with the refusal's text when there is one. It SHALL NOT be retried.

#### Scenario: A refusal
- **WHEN** a response's message has the refusal `I can't help with that.`
- **THEN** the run ends with an `error` result whose message says the model refused and holds `I can't help with
  that.`

#### Scenario: A content filter
- **WHEN** a response finishes with `content_filter`
- **THEN** the run ends with an `error` result saying the service's content filter stopped the response

### Requirement: An unexpected finish ends the run with an error
A response finishing with `length`, or with a finish reason the runner doesn't know and no tool call, SHALL end the
run with an `error` result naming the finish reason. A response that ends without one SHALL be treated as a broken
stream.

#### Scenario: The output limit
- **WHEN** a response finishes with `length`
- **THEN** the run ends with an `error` result saying the response reached the service's output limit

#### Scenario: An unknown finish reason
- **WHEN** a response finishes with `paused` and asks for no tool call
- **THEN** the run ends with an `error` result naming `paused`

### Requirement: Usage is summed into the result
The result SHALL carry the run's usage summed over every response: `inputTokens` as the input tokens less those read
from the service's cache, `cacheReadTokens` as those cached tokens, and `outputTokens`. When a response reports no
usage, the result SHALL carry no usage and the runner SHALL say so in a `log` warning.

#### Scenario: Two responses with cached input
- **WHEN** one response reports 100 prompt tokens, 40 of them cached, and 10 completion tokens, and a second reports
  200 prompt tokens, none cached, and 20 completion tokens
- **THEN** the result's usage is `inputTokens` 260, `cacheReadTokens` 40 and `outputTokens` 30

#### Scenario: A service that reports no usage
- **WHEN** a response's stream ends without a usage record
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
loopback address, with `openai-chat.insecure-endpoint` naming the endpoint, and send nothing.

#### Scenario: Plain HTTP to another host
- **WHEN** a run's runtime has a credential and the endpoint `http://models.example.com/v1`
- **THEN** `run/start` is refused with `openai-chat.insecure-endpoint`, and no request is sent

#### Scenario: Plain HTTP to this machine
- **WHEN** a run's runtime has a credential and the endpoint `http://127.0.0.1:11434/v1`
- **THEN** the run starts and its requests go to that endpoint

### Requirement: Redirects are never followed
A response that redirects SHALL NOT be followed. The run SHALL end with an `error` result naming the status and the
location it pointed to, so neither the credential nor the conversation is sent anywhere the runtime didn't name.

#### Scenario: A redirect to another host
- **WHEN** the endpoint answers 307 with `Location: https://elsewhere.example/v1/chat/completions`
- **THEN** no request reaches `elsewhere.example`, and the run ends with an `error` result naming 307 and that
  location

### Requirement: Transient failures are retried and reported
A request that fails with a rate limit (429), a server error (500 or above), a network error or a timeout SHALL be
retried up to the runner's named maximum attempts, with a growing delay, each retry reported first as a `retry` event
with reason `rate-limit`, `server` or `network`. When the attempts run out, the run SHALL end with an `error` result.

#### Scenario: A server error, then success
- **WHEN** the first request is answered 503 and the second succeeds
- **THEN** a `retry` event with attempt 1, reason `server` and the delay comes before the second request, and the run
  goes on

#### Scenario: Retries run out
- **WHEN** every attempt is answered 500
- **THEN** after the last attempt the run ends with an `error` result naming the status and the attempts made

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

#### Scenario: The context is too long
- **WHEN** a request is answered 400 with the error code `context_length_exceeded`
- **THEN** it isn't retried, and the run ends with an `error` result saying the conversation is longer than the
  model's context

### Requirement: A broken stream is retried as a network failure
A response stream that ends before its finish reason, holds a line that isn't a valid event, or goes silent for the
runner's named stream timeout SHALL be dropped whole, including any tool calls it had begun, and the request retried
as a network failure.

#### Scenario: The connection drops mid-response
- **WHEN** a response's stream stops after half a tool call's arguments
- **THEN** no `tool_call` event is sent for it, a `retry` with reason `network` follows, and the retried response is
  used instead

#### Scenario: The stream goes quiet
- **WHEN** a response sends nothing for longer than the stream timeout
- **THEN** the request is abandoned and retried, with a `retry` event with reason `network`

### Requirement: The transcript is the exchange with the service
The runner SHALL send, as `run/transcript` records in the order they happen, each request body as sent, each line of
each response's stream unchanged, and each error response's body, each in a record that says which it is. Request and
response headers SHALL NOT be recorded, except the response headers the runner names in one place.

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
On `run/cancel`, or when its standard input closes, the runner SHALL abandon any request in flight, send no further
request, and exit within troupe's cancel grace period. After a cancel it SHALL send no `result`.

#### Scenario: Cancel during a slow response
- **WHEN** the host cancels a run while the fake endpoint is holding a response open
- **THEN** the runner acknowledges the cancel, the endpoint sees its connection closed, and the runner exits without
  a `result`

### Requirement: The runner publishes its schemas
The runner SHALL publish its options schema and its error codes' schema, each passing the protocol's strictness
check. Its error codes SHALL include `openai-chat.unknown-option`, `openai-chat.invalid-options`,
`openai-chat.no-runtime` and `openai-chat.insecure-endpoint`.

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
- **THEN** there is at least a run with tool calls that succeeds, a rejected credential, a rate limit, a server
  error, a broken stream and a refusal, and each names its service and whether it was recorded, derived or built

#### Scenario: A fixture built from documentation
- **WHEN** a fixture's responses weren't recorded
- **THEN** its provenance names what it was derived from, or the documentation page its shape was built from

### Requirement: Fixtures hold no secrets
No committed fixture SHALL contain a credential, an account or organisation id, or a host path outside the fixture.

#### Scenario: A secret in a fixture
- **WHEN** a fixture contains a string matching a credential pattern or the capturing host's home path
- **THEN** the fixture test fails, naming the fixture and the line

### Requirement: Failure fixtures are captured without a real credential
The capture tool SHALL capture every fixture it can without a working credential: against a local
OpenAI-compatible server, or against the real service with a deliberately invalid key. Only a fixture that needs a
working credential SHALL use one, and the owner captures it.

#### Scenario: A rejected credential fixture
- **WHEN** the capture tool captures the rejected-credential fixture
- **THEN** it sends a deliberately invalid key, and the fixture's provenance says no working credential was used

### Requirement: A live test runs a real service only when asked
An opt-in test SHALL run the runner against a real service. It SHALL run only when `TROUPE_LIVE_OPENAI_CHAT` is `1`,
never in CI, with a model pinned in one place and a small token budget and turn limit. It SHALL name the endpoint and
model it used.

#### Scenario: Not asked
- **WHEN** the test suite runs without `TROUPE_LIVE_OPENAI_CHAT`
- **THEN** the live test is skipped, saying how to run it

#### Scenario: A live run
- **WHEN** the owner runs it with `TROUPE_LIVE_OPENAI_CHAT=1` and a runtime with a working credential
- **THEN** a run that writes and reads back a file ends `succeeded` within its token budget, and the file holds what
  was asked
