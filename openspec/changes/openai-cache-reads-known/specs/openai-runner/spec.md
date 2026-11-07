## MODIFIED Requirements

### Requirement: Usage is summed into the result
The result SHALL carry the run's usage summed over every response: `outputTokens`; `cacheReadTokens` as the input
tokens read from the service's cache and `cacheWriteTokens` as those written to it, each only when every response
reports it; and `inputTokens` as the input tokens less each cache counter the result carries. When a response reports
no usage, the result SHALL carry no usage and the runner SHALL say so in a `log` warning.

#### Scenario: Two responses with cached input
- **WHEN** one response reports 100 input tokens, 40 of them cached, and 10 output tokens, and a second reports 200
  input tokens, none cached, and 20 output tokens
- **THEN** the result's usage is `inputTokens` 260, `cacheReadTokens` 40 and `outputTokens` 30

#### Scenario: Tokens written to the cache
- **WHEN** a response reports 300 input tokens, 100 of them cached and 50 written to the cache, and 10 output tokens
- **THEN** the result's usage is `inputTokens` 150, `cacheReadTokens` 100, `cacheWriteTokens` 50 and
  `outputTokens` 10

#### Scenario: Cache writes reported by only one of two responses
- **WHEN** one response reports 100 input tokens, 40 of them cached and 20 written to the cache, and 10 output tokens,
  and a second reports 200 input tokens, none cached, no count of tokens written to the cache, and 20 output tokens
- **THEN** the result's usage is `inputTokens` 260, `cacheReadTokens` 40 and `outputTokens` 30, with no
  `cacheWriteTokens`

#### Scenario: Cached tokens reported by only one of two responses
- **WHEN** one response reports 100 input tokens, 40 of them cached, and 10 output tokens, and a second reports 200
  input tokens, no count of cached tokens, and 20 output tokens
- **THEN** the result's usage is `inputTokens` 300 and `outputTokens` 30, with no `cacheReadTokens`

#### Scenario: Cache writes reported but cached tokens not
- **WHEN** a response reports 300 input tokens, 50 of them written to the cache, no count of cached tokens, and 10
  output tokens
- **THEN** the result's usage is `inputTokens` 250, `cacheWriteTokens` 50 and `outputTokens` 10, with no
  `cacheReadTokens`

#### Scenario: A cached count that isn't a whole number of tokens
- **WHEN** a response reports 300 input tokens, its count of cached tokens as `-1` or as the string `"40"`, and 10
  output tokens
- **THEN** the result's usage is `inputTokens` 300 and `outputTokens` 10, with no `cacheReadTokens`

#### Scenario: A service that reports nothing about its cache
- **WHEN** a response reports 420 input tokens and 10 output tokens, with no input token details
- **THEN** the result's usage is `inputTokens` 420 and `outputTokens` 10, with neither cache counter

#### Scenario: A service that reports no usage
- **WHEN** a response completes without usage
- **THEN** a `log` warning says the service reported no usage, so only the turn limit bounds the run, and the result
  has no `usage`
