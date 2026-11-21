## ADDED Requirements

### Requirement: The runner counts by its runtime's engine and never guesses it
The runner SHALL take a run's engine only from `run/start`'s `runtime.engine` (spec: runtimes), and SHALL NOT infer
it from the endpoint or a reply's headers, ids or model. One table SHALL say, for each engine the protocol names,
whether its `input_tokens` includes cache reads, or that this isn't known, each entry naming the fixture, probe or
documentation that pins it. With no engine, the accounting SHALL be taken as not known.

#### Scenario: A runtime that names LM Studio
- **WHEN** `run/start`'s runtime has `engine` `lm-studio`
- **THEN** the run counts LM Studio's cache reads as inside its `input_tokens`

#### Scenario: A runtime that names no engine
- **WHEN** `run/start`'s runtime has no `engine` and the endpoint is `http://127.0.0.1:1234`
- **THEN** the run's accounting is not known, even when the replies look like LM Studio's

#### Scenario: The table pins each engine's accounting
- **WHEN** the table is read
- **THEN** it holds one entry for each engine in the protocol's set: Claude's API and Ollama report cache reads apart
  from `input_tokens`, LM Studio inside it, and llama.cpp not yet known, and each entry names what it's taken from

### Requirement: Cache reads on an engine of unknown accounting are warned about once
When the run's accounting isn't known, the first reply that reports `cache_read_input_tokens` above zero SHALL bring a
`log` warning, sent once in the run, saying the usage may count those tokens twice. With no engine it SHALL name the
runtime and its `engine` field as the fix. A run whose replies report no cache reads SHALL bring no such warning.

#### Scenario: Cache reads on a runtime with no engine
- **WHEN** the runtime names no engine and the second reply reports 89 cache-read tokens
- **THEN** one `log` warning names the runtime's `engine` field, and no second one follows a later reply's cache
  reads

#### Scenario: No cache reads
- **WHEN** the runtime names no engine and every reply reports 0 cache-read tokens
- **THEN** no warning about the engine is sent

#### Scenario: A named engine
- **WHEN** the runtime's engine is `lm-studio` and a reply reports cache reads
- **THEN** no warning about the engine is sent

### Requirement: An engine's cache reads are counted once
On an engine the table says counts cache reads inside `input_tokens`, each reply's `inputTokens` SHALL be its
`input_tokens` less its cache reads, so the result, the token budget and the estimated cost count each token once.
When the accounting isn't known, usage SHALL stay as the Messages API defines it.

#### Scenario: LM Studio's cache reads counted once
- **WHEN** a run on a runtime whose engine is `lm-studio` gets one reply reporting 93 input and 0 cache-read tokens, and a second 126
  input and 89 cache-read tokens (`fixtures/lm-studio-tool-loop`)
- **THEN** the result's usage is `inputTokens` 130 and `cacheReadTokens` 89

#### Scenario: The same replies with the engine unknown
- **WHEN** the runtime names no engine
- **THEN** the result's usage is `inputTokens` 219 and `cacheReadTokens` 89, as the API defines them

### Requirement: A reply's prompt is measured by the engine's accounting
A reply's prompt SHALL be its input and cache-write tokens, plus its cache-read tokens on an engine that reports them
apart from its input. When the accounting isn't known, the runner SHALL read it both ways: a prompt that shrank by
either reading SHALL be taken as cut, and the context window SHALL judge by the larger.

#### Scenario: LM Studio's cut on a turn that reports cache reads
- **WHEN** a run on a runtime whose engine is `lm-studio` gets a reply reporting 4,482 input and 115 cache-read tokens, then a reply
  from the cut conversation reporting 4,037 input and 3,840 cache-read tokens (`fixtures/lm-studio-conversation-cut`,
  replies 1 and 4)
- **THEN** the second reply is taken as cut, since its prompt of 4,037 is smaller than 4,482, and nothing in it is
  acted on

#### Scenario: The same cut with the engine unknown
- **WHEN** the same replies come in a run whose runtime names no engine
- **THEN** the second reply is taken as cut, since its input alone shrank, though input and cache reads together grew

#### Scenario: Claude's cache reads rising
- **WHEN** a run on a runtime whose engine is `claude` gets a reply reporting 900 input and 0 cache-read tokens, then one reporting 100 input
  and 1,000 cache-read tokens
- **THEN** the run goes on: the prompt grew from 900 to 1,100

## MODIFIED Requirements

### Requirement: Usage is summed into the result
The result SHALL carry the run's usage summed over every reply as the Messages API defines it: `inputTokens` from
`input_tokens`, `cacheReadTokens` from `cache_read_input_tokens` and `cacheWriteTokens` from
`cache_creation_input_tokens`, each cache counter only when every reply reports it, and `outputTokens`, after the
engine's correction ("An engine's cache reads are counted once"). A reply with no usage SHALL make the result carry
none, with a `log` warning.

#### Scenario: Two replies with cached input
- **WHEN** one reply reports 60 input, 40 cache-read and 10 output tokens, and a second 200 input, 0 cache-read and 20
  output tokens
- **THEN** the result's usage is `inputTokens` 260, `cacheReadTokens` 40 and `outputTokens` 30

#### Scenario: Cache writes reported by only one reply
- **WHEN** one reply reports `cache_creation_input_tokens` 50 and the other doesn't report it
- **THEN** the result has no `cacheWriteTokens`

### Requirement: A reply from a conversation the engine shrank isn't acted on
The conversation only grows, so a reply whose reported prompt ("A reply's prompt is measured by the engine's
accounting") is smaller than the previous request's SHALL be taken as made from a conversation the engine cut. No
`turn` or tool call from it SHALL be sent, and a run told `fail` SHALL end with `error` and `reason` `context-length`. A first request has no earlier prompt, so an engine that cuts it silently isn't caught, and
the README SHALL say so.

#### Scenario: An engine that cuts the middle
- **WHEN** a run's second request is reported as 5,900 prompt tokens and its third, which adds a tool result to it, as
  4,058
- **THEN** no `turn` or `tool_call` event is sent for the third reply, and the run ends with `error` and `reason`
  `context-length`, saying the engine answered from less of the conversation than it was sent

#### Scenario: A conversation that grows
- **WHEN** each reply reports a larger prompt than the one before
- **THEN** the run goes on

#### Scenario: A first request an engine cut
- **WHEN** a run's first request is over an engine's window, and the engine cuts it and answers, as Ollama does
- **THEN** the runner can't tell, and acts on the reply: the README names this limit and the engines it's proved
  against that refuse such a request instead (Claude's API and LM Studio)

### Requirement: A run stops before the context window the person named
When `contextWindow` is set, a reply whose reported prompt and output reach it SHALL be acted on, and the runner SHALL
send no further request in a run told `fail`, ending it with `error` and `reason` `context-length`, naming the
window. A reply whose reported prompt alone reaches it SHALL NOT be acted on. The prompt SHALL be measured as the
shrinking-prompt guard measures it, and, when the accounting isn't known, by the larger reading.

#### Scenario: The window is reached
- **WHEN** a run with `contextWindow` 8192 gets a reply asking for a tool call, reported as 7,900 prompt tokens and 300
  output tokens
- **THEN** the call is carried out, no further request is sent, and the run ends with `error` and `reason`
  `context-length`

#### Scenario: No window named
- **WHEN** a run's options don't set `contextWindow`
- **THEN** only the engine's refusals and a shrinking prompt end the run for its context

#### Scenario: LM Studio's cache reads don't fill the window
- **WHEN** a run on a runtime whose engine is `lm-studio` and `contextWindow` 8192 gets a reply reporting 5,000 input tokens, 4,000 of
  them cache reads, and 100 output tokens
- **THEN** the window isn't reached: the prompt is 5,000, not 9,000
