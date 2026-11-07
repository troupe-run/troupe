# Spec Delta

## MODIFIED Requirements

### Requirement: A broken stream is retried as a network failure
A response stream cut short SHALL be dropped whole, including any tool calls it had begun, and the request retried as
a network failure. A stream is cut short when it ends before a final event (`response.completed`,
`response.incomplete`, `response.failed` or `error`), ends inside an event whose data isn't whole JSON, breaks, or
goes silent for the runner's named stream timeout.

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

### Requirement: The transcript is the exchange with the service
The runner SHALL send, as `run/transcript` records in the order they happen, each request body as sent, each line of
each response's stream unchanged, its `event:` lines included, and the body of each error response and of each
successful response that isn't a stream, each in a record that says which it is. Request and response headers SHALL
NOT be recorded, except the response headers the runner names in one place.

#### Scenario: A run's transcript
- **WHEN** a run makes one request and gets one streamed response
- **THEN** its transcript holds a record of the request body, then one record for each line of the response's
  stream, in order

#### Scenario: No request header
- **WHEN** any transcript record is read
- **THEN** none holds a request header

#### Scenario: A successful answer that isn't a stream
- **WHEN** a request is answered 200 with `Content-Type: application/json`
- **THEN** the transcript holds a record of that response's body

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
  rejected credential, a rate limit, a server error, a broken stream, an incomplete response, a refusal and a response
  finished in the wrong shape, and each names its service and whether it was recorded, derived or built

#### Scenario: A fixture built from documentation
- **WHEN** a fixture's responses weren't recorded
- **THEN** its provenance names what it was derived from, or the documentation page its shape was built from

## ADDED Requirements

### Requirement: A response finished in the wrong shape ends the run
A response the service finished but the runner can't read SHALL end the run at once with an `error` result saying
the service's response can't be read and naming what was wrong, and SHALL NOT be retried. No tool call from it SHALL
be carried out. An event is finished when its blank line arrived or its data is whole JSON.

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

### Requirement: A successful answer that isn't a stream ends the run
A 2xx response whose `Content-Type` is present and isn't `text/event-stream` SHALL end the run at once with an
`error` result naming the status and the content type, and holding the service's message when the body is in
OpenAI's error shape, or else the start of the body. It SHALL NOT be retried. A 2xx response with no `Content-Type`
SHALL be read as a stream.

#### Scenario: A plain JSON body
- **WHEN** a request is answered 200 with `Content-Type: application/json` and a JSON response object
- **THEN** no `retry` event is sent, and the run ends with an `error` result naming 200 and `application/json`, and
  saying the runner asked for a stream

#### Scenario: A stream's content type with parameters
- **WHEN** a request is answered 200 with `Content-Type: text/event-stream; charset=utf-8` and a well-formed stream
- **THEN** the stream is read and the run goes on

#### Scenario: No content type
- **WHEN** a request is answered 200 with no `Content-Type` and a well-formed stream
- **THEN** the stream is read and the run goes on

### Requirement: A wrong-shaped response's usage is counted
When a final event ends the run for its shape and its response's `usage` can still be read, the result's usage, and
its cost when the service reports one, SHALL include that response's, as they include every other response's.

#### Scenario: Readable usage beside unreadable output
- **WHEN** a run's first response asks for a tool call and reports 100 input and 10 output tokens, and its second
  response's output isn't a list and its usage reports 200 input and 20 output tokens
- **THEN** the run ends with an `error` result whose usage has `inputTokens` 300 and `outputTokens` 30
