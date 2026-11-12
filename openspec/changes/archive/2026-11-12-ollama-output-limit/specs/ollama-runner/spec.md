## ADDED Requirements

### Requirement: A cut answer ends the run
An answer that ends with `done_reason` `length` SHALL end the run with an `error` result whose message says Ollama cut
the answer at its output limit and names the run's context window and `contextLength`. The runner SHALL make no
further request, carry out none of that answer's tool calls, and not retry it. The answer's text SHALL still be a
`turn`, and its lines transcript records.

#### Scenario: A cut text answer
- **WHEN** an answer streams the text `The first part` with no tool call, and ends with `done_reason` `length`
- **THEN** the runner sends a `turn` holding `The first part`, then an `error` `result` naming the window and
  `contextLength`, and sends no `log` warning

#### Scenario: A cut tool call
- **WHEN** an answer holds a `Write` call and ends with `done_reason` `length`
- **THEN** the runner sends no `tool_call` or `tool_result`, writes no file, makes no further request, and sends an
  `error` `result`

#### Scenario: Not retried
- **WHEN** an answer ends with `done_reason` `length`
- **THEN** the runner sends no `retry` event, and the run made exactly the requests up to that answer

#### Scenario: The tokens Ollama produced
- **WHEN** a cut answer's last line has `eval_count` 81
- **THEN** the `result`'s message says the answer was cut after 81 tokens

#### Scenario: A cut answer captured from Ollama
- **WHEN** the `cut-answer` or `cut-tool-call` fixture is replayed
- **THEN** the runner sends exactly the fixture's events, ending with an `error` `result` whose reason is
  `output-limit`

### Requirement: Each failed run reports its reason
Every `error` result the Ollama runner sends SHALL carry a reason from one table in the runner: Ollama refusing a
request over the context window `context-length`, an answer Ollama cut (`done_reason` `length`) `output-limit`, the
turn limit `turn-limit`, 401 or 403 `authentication`, 404 `configuration`, retries run out the last retry's reason, an
`error` record in a stream `engine`, the runner's own unexpected failure `runner`, and any other refused request
`other`.

#### Scenario: A conversation that outgrows the window
- **WHEN** Ollama answers a request with status 400 and a message saying the request exceeds the available context
  size
- **THEN** the `result` has status `error` and `reason` `context-length`

#### Scenario: Another refused request
- **WHEN** Ollama answers a request with status 400 and a message that doesn't mention the context size
- **THEN** the `result` has `reason` `other`, and its message doesn't name the context window

#### Scenario: The turn limit
- **WHEN** `maxTurns` is 2 and both answers hold tool calls
- **THEN** the `result` has `reason` `turn-limit`

#### Scenario: A refused credential
- **WHEN** an Ollama behind a proxy answers a request with status 401
- **THEN** the `result` has `reason` `authentication`

#### Scenario: A model removed after the check
- **WHEN** Ollama answers a chat request with status 404
- **THEN** the `result` has `reason` `configuration`

#### Scenario: Retries spent on a busy server
- **WHEN** every attempt gets status 503
- **THEN** the `result` has `reason` `server`

#### Scenario: A dropped connection on every attempt
- **WHEN** every attempt's connection closes before the stream's final record
- **THEN** the `result` has `reason` `network`

#### Scenario: An error part-way through a stream
- **WHEN** a stream sends text and then a record holding only `error`
- **THEN** the `result` has `reason` `engine`

#### Scenario: The runner fails
- **WHEN** the runner raises an exception it didn't expect during a run
- **THEN** the `result` has `reason` `runner`

#### Scenario: A cut answer
- **WHEN** an answer ends with `done_reason` `length` and holds no tool call
- **THEN** the run ends with an `error` result whose `reason` is `output-limit`, and sends no `log` warning

## MODIFIED Requirements

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
- **THEN** the run ends with an `error` result, as a cut answer does

### Requirement: The loop ends when the model stops calling tools
The runner SHALL keep making requests while answers hold tool calls. An answer with no tool call SHALL end the run
with an `ok` result whose message is the answer's text, unless Ollama cut it. Reaching `maxTurns` requests, by default
a named setting of 50, SHALL end it with an `error` result saying the limit was reached.

#### Scenario: A final answer
- **WHEN** the model's answer holds text and no tool call
- **THEN** the runner sends an `ok` `result` whose message is that text, and makes no further request

#### Scenario: A cut final answer
- **WHEN** the model's answer holds text and no tool call, and ends with `done_reason` `length`
- **THEN** the runner sends an `error` `result`, not an `ok` one

#### Scenario: The turn limit
- **WHEN** `maxTurns` is 2 and both answers hold tool calls
- **THEN** after carrying out the second answer's calls the runner sends an `error` `result` naming the limit of 2,
  and makes no third request

## REMOVED Requirements

### Requirement: Each failure reports its reason
**Reason**: Replaced by "Each failed run reports its reason", which adds `output-limit` for a cut answer. Its
scenario "A cut answer is still not a failure" is no longer true, and a MODIFIED block can't drop a scenario.
**Migration**: None: that requirement keeps every other scenario of this one as it was.
