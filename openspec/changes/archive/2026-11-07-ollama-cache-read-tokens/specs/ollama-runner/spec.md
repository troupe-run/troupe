# Spec Delta

## MODIFIED Requirements

### Requirement: The result carries the run's counts
The `result` SHALL carry the number of requests as `turns`, the run's duration, and as `usage`, summed over every
request: Ollama's generated token count as `outputTokens`, its cached prompt token count as `cacheReadTokens`, and its
prompt token count less the cached count as `inputTokens`, leaving out a counter no request reported. Unless every
request reported a cached count beside its prompt count, `cacheReadTokens` SHALL be left out and nothing subtracted. It
SHALL carry no cost.

#### Scenario: Two requests
- **WHEN** a run's two requests report prompt counts 120 and 300, and generated counts 40 and 25, and no cached counts
- **THEN** its `result` has `turns` 2 and `usage` `{"inputTokens": 420, "outputTokens": 65}`, and no `costUsd`

#### Scenario: Prompt tokens served from the cache
- **WHEN** a run's two requests report prompt counts 1222 and 1276, cached counts 88 and 1218, and generated counts 33
  and 23
- **THEN** its `result` has `usage` `{"inputTokens": 1192, "outputTokens": 56, "cacheReadTokens": 1306}`

#### Scenario: A request that reports no cached count
- **WHEN** a run's first request reports prompt count 120 with cached count 20, and its second reports prompt count
  300 with no cached count
- **THEN** its `result`'s `usage` has `inputTokens` 420 and no `cacheReadTokens`

#### Scenario: A cached count with no prompt count
- **WHEN** a run's only request reports a cached count 50 and generated count 7, and no prompt count
- **THEN** its `result` has `usage` `{"outputTokens": 7}`

#### Scenario: A cached count larger than its prompt count
- **WHEN** a run's only request reports prompt count 10 and cached count 12
- **THEN** its `result`'s `usage` has `inputTokens` 0 and `cacheReadTokens` 10, the cached count cut to the prompt
  count
