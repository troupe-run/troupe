## ADDED Requirements

### Requirement: The runner is told its engine and never guesses it
The runner SHALL know a run's engine only from its `engine` option, or from a runtime endpoint of
`https://api.anthropic.com`, which is Claude's API. With neither, the engine SHALL be unknown, and the runner SHALL NOT
infer it from a reply's headers, ids or model. Each engine's usage accounting SHALL be named in one table, each entry
naming the fixture, probe or documentation that pins it.

#### Scenario: Claude's built-in endpoint
- **WHEN** the runtime's endpoint is `https://api.anthropic.com` and the options don't set `engine`
- **THEN** the run's engine is Claude's API

#### Scenario: A local engine named
- **WHEN** the options set `engine` to `lm-studio`
- **THEN** the run's engine is LM Studio, whatever the endpoint

#### Scenario: A local engine not named
- **WHEN** the endpoint is `http://127.0.0.1:1234` and the options don't set `engine`
- **THEN** the run's engine is unknown, even when the replies look like LM Studio's

#### Scenario: The table pins each engine's accounting
- **WHEN** the table is read
- **THEN** it says that Claude's API, Ollama and llama.cpp report cache reads apart from `input_tokens` and LM Studio
  inside it, and each entry names what it's taken from

### Requirement: An unknown engine's cache reads are warned about once
When the engine is unknown, the first reply that reports `cache_read_input_tokens` above zero SHALL bring a `log`
warning, sent once in the run, saying the usage may count those tokens twice and naming the `engine` option. A run
whose replies report no cache reads SHALL bring no such warning.

#### Scenario: Cache reads on an unnamed engine
- **WHEN** the engine is unknown and the second reply reports 89 cache-read tokens
- **THEN** one `log` warning names the `engine` option, and no second one follows a later reply's cache reads

#### Scenario: No cache reads
- **WHEN** the engine is unknown and every reply reports 0 cache-read tokens
- **THEN** no warning about the engine is sent

## MODIFIED Requirements

### Requirement: The runner's options are closed
`run/start` options SHALL be an object with only `maxTurns`, `maxTotalTokens`, `maxOutputTokens`, `contextWindow` and
`engine`, each optional. The first four SHALL each be a positive integer, and `engine` one of `claude`, `lm-studio`,
`ollama` and `llama.cpp`. An option the runner doesn't define, or a value of the wrong shape, SHALL be refused with an
error naming it, and no request SHALL be sent.

#### Scenario: An unknown option
- **WHEN** the options hold `troupeConformanceUnknownOption`
- **THEN** `run/start` is refused with `anthropic.unknown-option`, whose `details.where` names the option

#### Scenario: A malformed value
- **WHEN** `maxOutputTokens` is `0` or `contextWindow` is `"big"`
- **THEN** `run/start` is refused with `anthropic.invalid-options`, whose `details.where` names the option and whose
  fix names what is valid

#### Scenario: An engine the runner doesn't know
- **WHEN** `engine` is `lmstudio` or `LM Studio`
- **THEN** `run/start` is refused with `anthropic.invalid-options`, whose `details.where` names `engine` and whose fix
  names the engines it takes, rather than the run going on with the engine unknown

### Requirement: Usage is summed into the result
The result SHALL carry the run's usage summed over every reply as the Messages API defines it: `inputTokens` from
`input_tokens`, `cacheReadTokens` from `cache_read_input_tokens` and `cacheWriteTokens` from
`cache_creation_input_tokens`, each cache counter only when every reply reports it, and `outputTokens`. On an engine
the table says counts cache reads inside `input_tokens`, each reply's `inputTokens` SHALL be its `input_tokens` less
its cache reads, so the result, the token budget and the estimated cost count each token once. A reply with no usage
SHALL make the result carry none, with a `log` warning.

#### Scenario: Two replies with cached input
- **WHEN** one reply reports 60 input, 40 cache-read and 10 output tokens, and a second 200 input, 0 cache-read and 20
  output tokens
- **THEN** the result's usage is `inputTokens` 260, `cacheReadTokens` 40 and `outputTokens` 30

#### Scenario: Cache writes reported by only one reply
- **WHEN** one reply reports `cache_creation_input_tokens` 50 and the other doesn't report it
- **THEN** the result has no `cacheWriteTokens`

#### Scenario: LM Studio's cache reads counted once
- **WHEN** a run with `engine` `lm-studio` gets one reply reporting 93 input and 0 cache-read tokens, and a second 126
  input and 89 cache-read tokens (`fixtures/lm-studio-tool-loop`)
- **THEN** the result's usage is `inputTokens` 130 and `cacheReadTokens` 89

#### Scenario: The same replies with the engine unknown
- **WHEN** the options don't name the engine and the endpoint isn't Claude's
- **THEN** the result's usage is `inputTokens` 219 and `cacheReadTokens` 89, as the API defines them

### Requirement: A reply from a conversation the engine shrank isn't acted on
The conversation only grows, so a reply whose reported prompt is smaller than the previous request's SHALL be taken as
made from a conversation the engine cut. A reply's prompt is its input and cache-write tokens, plus its cache-read
tokens on an engine that reports them apart. With the engine unknown, a prompt that shrank by either reading SHALL be
taken as cut. No `turn` or tool call from such a reply SHALL be sent, and a run told `fail` SHALL end with `error` and
`reason` `context-length`. A first request has no earlier prompt, so an engine that cuts it silently isn't caught, and
the README SHALL say so.

#### Scenario: An engine that cuts the middle
- **WHEN** a run's second request is reported as 5,900 prompt tokens and its third, which adds a tool result to it, as
  4,058
- **THEN** no `turn` or `tool_call` event is sent for the third reply, and the run ends with `error` and `reason`
  `context-length`, saying the engine answered from less of the conversation than it was sent

#### Scenario: A conversation that grows
- **WHEN** each reply reports a larger prompt than the one before
- **THEN** the run goes on

#### Scenario: LM Studio's cut on a turn that reports cache reads
- **WHEN** a run with `engine` `lm-studio` gets a reply reporting 4,482 input and 115 cache-read tokens, then a reply
  from the cut conversation reporting 4,037 input and 3,840 cache-read tokens (`fixtures/lm-studio-conversation-cut`,
  replies 1 and 4)
- **THEN** the second reply is taken as cut, since its prompt of 4,037 is smaller than 4,482, and nothing in it is
  acted on

#### Scenario: The same cut with the engine unknown
- **WHEN** the same replies come in a run whose engine is unknown
- **THEN** the second reply is taken as cut, since its input alone shrank, though input and cache reads together grew

#### Scenario: Claude's cache reads rising
- **WHEN** a run on Claude's API gets a reply reporting 900 input and 0 cache-read tokens, then one reporting 100 input
  and 1,000 cache-read tokens
- **THEN** the run goes on: the prompt grew from 900 to 1,100

#### Scenario: A first request an engine cut
- **WHEN** a run's first request is over an engine's window, and the engine cuts it and answers, as Ollama does
- **THEN** the runner can't tell, and acts on the reply: the README names this limit and the engines it's proved
  against that refuse such a request instead (Claude's API and LM Studio)

### Requirement: A run stops before the context window the person named
When `contextWindow` is set, a reply whose reported prompt and output reach it SHALL be acted on, and the runner SHALL
send no further request in a run told `fail`, ending it with `error` and `reason` `context-length`, naming the
window. A reply whose reported prompt alone reaches it SHALL NOT be acted on. The prompt SHALL be measured as the
shrinking-prompt guard measures it, and with the engine unknown by the larger reading.

#### Scenario: The window is reached
- **WHEN** a run with `contextWindow` 8192 gets a reply asking for a tool call, reported as 7,900 prompt tokens and 300
  output tokens
- **THEN** the call is carried out, no further request is sent, and the run ends with `error` and `reason`
  `context-length`

#### Scenario: No window named
- **WHEN** a run's options don't set `contextWindow`
- **THEN** only the engine's refusals and a shrinking prompt end the run for its context

#### Scenario: LM Studio's cache reads don't fill the window
- **WHEN** a run with `engine` `lm-studio` and `contextWindow` 8192 gets a reply reporting 5,000 input tokens, 4,000 of
  them cache reads, and 100 output tokens
- **THEN** the window isn't reached: the prompt is 5,000, not 9,000
