## ADDED Requirements

### Requirement: Usage's input counters add up to the whole input
A `result` event's `inputTokens` SHALL count the input tokens not counted in `cacheReadTokens` or `cacheWriteTokens`,
so that the three add up to the run's whole input as the engine reported it. A runner SHALL subtract from its engine's
input count whatever that count includes of the cache's reads and writes. The contract's schema SHALL say this in the
descriptions of `usage` and its counters.

#### Scenario: An engine whose input count leaves the cache out
- **WHEN** an engine reports 6 input tokens, 42158 read from its cache and 5737 written to it, its input count not
  including either
- **THEN** the runner's `result` usage is `inputTokens` 6, `cacheReadTokens` 42158 and `cacheWriteTokens` 5737

#### Scenario: An engine whose input count includes the cache
- **WHEN** an engine reports 300 input tokens, of which 100 were read from its cache and 50 written to it
- **THEN** the runner's `result` usage is `inputTokens` 150, `cacheReadTokens` 100 and `cacheWriteTokens` 50

#### Scenario: The schema states the meaning
- **WHEN** a runner's author reads `usage` in the contract's `run-event.schema.json`
- **THEN** `inputTokens`' description says it leaves out the tokens counted in `cacheReadTokens` and
  `cacheWriteTokens`, and `usage`'s description says the three add up to the whole input

### Requirement: A cache counter left out was not reported
A runner SHALL leave out a cache counter it can't report, and SHALL NOT estimate one. Input its engine counted that the
runner can't separate into a cache counter SHALL stay in `inputTokens`.

#### Scenario: Cache writes reported for only some requests
- **WHEN** a run's engine counts cache reads and writes within its input count, reports 100 cache reads over the run,
  reports cache writes for only some of its requests, and counts 300 input tokens in all
- **THEN** the runner's `result` usage is `inputTokens` 200 and `cacheReadTokens` 100, with no `cacheWriteTokens`

#### Scenario: An engine that reports nothing about its cache
- **WHEN** an engine reports 420 input tokens and nothing about a cache
- **THEN** the runner's `result` usage is `inputTokens` 420, with neither cache counter
