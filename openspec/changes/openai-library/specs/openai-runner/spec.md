## ADDED Requirements

### Requirement: The runner talks to its service only through the openai package
The runner SHALL send every request through the `openai` package, pinned to one version in the lock file, as a
streamed call to the Responses API, and SHALL use no HTTP client of its own. One module alone SHALL import the
package. The runner SHALL be installed as `troupe-run`'s `openai` extra, not in its base install.

#### Scenario: The one module that imports it
- **WHEN** the import contracts are checked
- **THEN** exactly one module of the runner imports `openai`, and a scratch module elsewhere in the runner that imports
  it fails the check

#### Scenario: The request is unchanged
- **WHEN** a run's first request is sent through the library
- **THEN** the fake endpoint receives a `POST` to the endpoint followed by `/responses` whose JSON body is the same
  object today's runner sends for the same run

#### Scenario: The extra
- **WHEN** `troupe-run`'s dependencies are read
- **THEN** `troupe-runner-openai` is in the `openai` extra and in `all`, and not in the base dependencies

### Requirement: The library's dependencies are licensed and installable everywhere troupe runs
Every package the runner depends on through `openai` SHALL pass the repository's licence check, and SHALL install on
Linux, macOS and Windows for every Python version troupe supports.

#### Scenario: The licence check
- **WHEN** `scripts/check.py` checks the lock file
- **THEN** `openai` and every package it pulls in are on a tier of the licence list, any weak-copyleft one from a
  package index

#### Scenario: Every platform
- **WHEN** CI installs `troupe-run[openai]` on Linux, macOS and Windows for each supported Python
- **THEN** it installs, and the runner answers `initialize`

### Requirement: The library finds nothing of its own
The runner SHALL give the library its base URL, its credential or the absence of one, its HTTP client and every
header itself, so that no environment variable the library would otherwise read (`OPENAI_API_KEY`,
`OPENAI_ADMIN_KEY`, `OPENAI_BASE_URL`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`, `OPENAI_CUSTOM_HEADERS`) changes where a
request goes or what it carries.

#### Scenario: Variables the library reads
- **WHEN** the runner's environment holds `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`
  and `OPENAI_CUSTOM_HEADERS`, and its runtime has no credential and the endpoint of the fake endpoint
- **THEN** every request reaches the fake endpoint with no `Authorization`, `OpenAI-Organization` or
  `OpenAI-Project` header and none of the custom headers, and no request goes to the variable's base URL

#### Scenario: A runtime credential beside the variable
- **WHEN** the runner's environment holds `OPENAI_API_KEY` and its runtime has the credential `sk-canary-0123456789`
- **THEN** every request's `Authorization` header is `Bearer sk-canary-0123456789`

### Requirement: The library's own logging stays out of the run's output
The runner SHALL keep the library's loggers off standard output and pass only their warnings and above to standard
error, masked and cut to fit, whatever `OPENAI_LOG` says. Warnings the library's models raise while serialising a
response in a shape they don't expect SHALL NOT reach standard error.

#### Scenario: Debug logging asked for
- **WHEN** the runner's environment holds `OPENAI_LOG=debug`
- **THEN** standard output holds only protocol messages, and standard error holds no request header

#### Scenario: A wrong-shaped response
- **WHEN** a response's tool call has arguments that are an object
- **THEN** the run ends as the wrong-shape requirement says, and standard error holds no serialiser warning

### Requirement: Every timeout the library applies is one of the runner's named settings
Every timeout the library applies (connect, read, write and pool) SHALL be set from the runner's named settings, never
left to the library's default, and the runner's README SHALL name each setting and its default.

#### Scenario: A held connection
- **WHEN** the fake endpoint accepts a request and sends nothing
- **THEN** the runner abandons it after its named stream timeout, not the library's ten-minute default, and retries
  it as `network`

### Requirement: The transcript is what the library exposes
The runner SHALL send as transcript records, in order and before the events they lead to: each request's parameters
as passed to the library (`sent`); each stream event as the library parsed it, serialised, and each error body or
2xx body that isn't a stream (`received`); and each response's status with the headers named in one place, and each
stream it abandons (`note`).

#### Scenario: A run's transcript
- **WHEN** a run makes one request and gets one streamed response
- **THEN** its transcript holds a `sent` record of the request's parameters, then a `note` of the response's status,
  then one `received` record for each event of the stream, in order

#### Scenario: No request header
- **WHEN** any transcript record is read
- **THEN** none holds a request header

#### Scenario: An error response
- **WHEN** a request is answered 429 with a JSON body
- **THEN** the transcript holds a `note` naming status 429 and the kept headers, then a `received` record holding
  that body

#### Scenario: A successful answer that isn't a stream
- **WHEN** a request is answered 200 with `Content-Type: application/json`
- **THEN** the transcript holds a `received` record that is that response's body

#### Scenario: A broken stream
- **WHEN** a response's stream breaks off and the runner abandons it
- **THEN** the transcript holds a `note` saying why, after the stream's last `received` event

### Requirement: A stream's lines are capped below the library
The runner SHALL refuse to read a line of a response's body longer than its named line limit, counting bytes as they
arrive, beneath the library, so an over-long stream is never read whole into memory. It SHALL ask for no content
encoding, and refuse a successful response sent encoded before reading its body. Either SHALL be dropped and retried
as a network failure, naming the limit. An error sent encoded SHALL end the run for its status.

#### Scenario: A line past the limit
- **WHEN** a response's stream sends a line longer than the runner's line limit
- **THEN** a `retry` with reason `network` follows, its message names the limit, and the runner never holds more than
  the limit and one read of that line

#### Scenario: A compressed response
- **WHEN** a response is sent with `Content-Encoding: gzip`, its one line past the limit once decoded
- **THEN** none of its body is read, and a `retry` with reason `network` follows, naming the encoding and the limit

#### Scenario: An error sent compressed
- **WHEN** a request is answered 401 with `Content-Encoding: gzip` and OpenAI's error shape
- **THEN** no `retry` is sent, and the run ends with an `error` result with `reason` `authentication`, holding the
  service's message

### Requirement: A body read whole stops at a named limit
A body the runner reads whole, an error's or a successful answer's that isn't a stream, SHALL be read no further than
the runner's named body limit, beneath the library, however its lines are split, and the run SHALL end as that status
or answer says.

#### Scenario: An error that never ends
- **WHEN** a request is answered 401 with a body of short lines that never ends
- **THEN** the runner reads no further than its body limit, sends no `retry`, and the run ends with an `error` result
  with `reason` `authentication`

## MODIFIED Requirements

### Requirement: Transient failures are retried and reported
A request that fails with a rate limit (429), a server error (500 or above), a network error or a timeout SHALL be
retried up to the runner's named maximum attempts, with a growing delay, each retry reported first as a `retry` event
with reason `rate-limit`, `server` or `network`. A server error's `Retry-After` SHALL set its delay, up to the runner's
named maximum delay. When the attempts run out, the run SHALL end with an `error` result. The library's own retries
SHALL be off, so these are the only retries.

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

#### Scenario: Only the runner retries
- **WHEN** every request is answered 500 and the runner's maximum attempts is 5
- **THEN** the fake endpoint receives exactly 5 requests, and the runner sends 4 `retry` events

### Requirement: A broken stream is retried as a network failure
A response stream cut short SHALL be dropped whole, including any tool calls it had begun, and the request retried as
a network failure. A stream is cut short when it ends before a final event (`response.completed`,
`response.incomplete`, `response.failed` or `error`) has arrived with its blank line, breaks, holds bytes that aren't
UTF-8, or goes silent for the runner's named stream timeout.

#### Scenario: The connection drops mid-response
- **WHEN** a response's stream stops after half a tool call's arguments
- **THEN** no `tool_call` event is sent for it, a `retry` with reason `network` follows, and the retried response is
  used instead

#### Scenario: The stream goes quiet
- **WHEN** a response sends nothing for longer than the stream timeout
- **THEN** the request is abandoned and retried, with a `retry` event with reason `network`

#### Scenario: The stream ends inside an event
- **WHEN** a response's stream ends after a `data:` line holding the first half of a `response.completed` event's
  JSON, with no blank line after it
- **THEN** a `retry` with reason `network` follows, and the retried response is used instead

#### Scenario: The stream ends before a final event's blank line
- **WHEN** a response's stream ends after a `data:` line holding a whole `response.completed` event, with no blank
  line after it
- **THEN** a `retry` with reason `network` follows, and the retried response is used instead

#### Scenario: Bytes that aren't UTF-8
- **WHEN** a line of a response's stream holds the byte `0xff`
- **THEN** a `retry` with reason `network` follows

### Requirement: A response finished in the wrong shape ends the run
A response the service finished but the runner can't read SHALL end the run at once with an `error` result saying
the service's response can't be read and naming what was wrong, and SHALL NOT be retried. No tool call from it SHALL
be carried out. An event is finished when its blank line arrived.

#### Scenario: Tool-call arguments sent as an object
- **WHEN** a response's `response.completed` event holds a `function_call` whose `arguments` is a JSON object rather
  than text
- **THEN** no `retry` event is sent and no `tool_call` event is sent, and the run ends with an `error` result saying
  the response can't be read because the tool call's arguments aren't text

#### Scenario: An event that isn't JSON
- **WHEN** a response's stream holds the line `data: not json` followed by a blank line
- **THEN** no `retry` event is sent, and the run ends with an `error` result saying an event in the response isn't
  JSON, quoting its start

#### Scenario: Output that isn't a list
- **WHEN** a response's `response.completed` event holds an `output` that is a number
- **THEN** the request is sent once, and the run ends with an `error` result saying the response's output isn't a
  list

### Requirement: Cancel and end of input stop the request in flight
On `run/cancel`, or when its standard input closes, the runner SHALL abandon any request in flight, carry out no further
tool call, send no further request, and exit within troupe's cancel grace period, whatever the library's timeouts
are. After a cancel it SHALL send no `result`.

#### Scenario: Cancel during a slow response
- **WHEN** the host cancels a run while the fake endpoint is holding a response open
- **THEN** the runner acknowledges the cancel, the endpoint sees its connection closed, and the runner exits within
  the grace without a `result`

#### Scenario: A stop between tool calls
- **WHEN** the run is stopped after the first of a response's two tool calls is carried out
- **THEN** the second isn't carried out, and no further request is sent

## REMOVED Requirements

### Requirement: The transcript is the exchange with the service
**Reason**: Decision #319: a library-backed runner's transcript keeps what the library exposes, not wire bytes. The
runner no longer reads the stream's bytes itself, so it can't record them.

**Migration**: Replaced by "The transcript is what the library exposes". A transcript reader that wanted each stream
line now gets each event as JSON, with no `event:` or blank lines; a `sent` record is the request's parameters as
compact JSON.
