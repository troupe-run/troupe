## ADDED Requirements

### Requirement: Each failure reports its reason
Every `error` result the Ollama runner sends SHALL carry a reason from one table in the runner: Ollama refusing a
request over the context window `context-length`, the turn limit `turn-limit`, 401 or 403 `authentication`, 404
`configuration`, retries run out the last retry's reason, an `error` record in a stream `engine`, the runner's own
unexpected failure `runner`, and any other refused request `other`.

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

#### Scenario: A cut answer is still not a failure
- **WHEN** an answer ends with `done_reason` `length` and the next answer holds no tool call
- **THEN** the runner sends a `log` warning, and the run ends with an `ok` result carrying no reason
