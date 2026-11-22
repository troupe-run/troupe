## ADDED Requirements

### Requirement: Status shows a run's tokens and cost
`troupe status <run>` SHALL show, after the run's event count, a `tokens:` line naming each token counter the run's
summary carries, and a `cost:` line with the amount and its kind: `reported by the service`, or, with `~` before the
amount, `estimated from the runtime's price`. A run whose summary has no `usage` SHALL show no `tokens:` line, and one
with no `cost` no `cost:` line.

#### Scenario: A run whose service reported its cost
- **WHEN** a person runs `troupe status <run>` for a run whose summary has `usage` of 1204 input, 9817 output, 182330
  cache-read and 14022 cache-write tokens, and `cost` 0.4213 `reported`
- **THEN** after `events:` the output shows
  `tokens: 1,204 input, 9,817 output, 182,330 cache read, 14,022 cache write` and
  `cost: $0.4213, reported by the service`

#### Scenario: A run whose cost was estimated
- **WHEN** a person runs `troupe status <run>` for a run whose summary has `usage` of 3410 input, 2066 output, 21504
  cache-read and 0 cache-write tokens, and `cost` 0.0136 `estimated`
- **THEN** the output shows `tokens: 3,410 input, 2,066 output, 21,504 cache read, 0 cache write` and
  `cost: ~$0.0136, estimated from the runtime's price`

#### Scenario: A run whose runner reported neither
- **WHEN** a person runs `troupe status <run>` for an Ollama run whose summary has no `usage` and no `cost`
- **THEN** the output has no `tokens:` line and no `cost:` line

#### Scenario: Tokens but no price
- **WHEN** a person runs `troupe status <run>` for an OpenAI run with no price, whose summary has `usage` and no `cost`
- **THEN** the output shows the `tokens:` line and no `cost:` line

#### Scenario: A counter the runner left out
- **WHEN** a person runs `troupe status <run>` for a run whose `usage` has no `cacheWriteTokens`
- **THEN** the `tokens:` line names input, output and cache read only, and never shows 0 cache write

### Requirement: The list of runs shows each run's cost
`troupe status` SHALL end a run's line with its cost when its summary carries one: the amount for a reported cost,
and `~` before the amount and `estimated` after it for an estimate. A run with no `cost` SHALL show none on its
line, and the list SHALL show no token counts.

#### Scenario: Runs with a reported cost, an estimate and neither
- **WHEN** a person runs `troupe status` and the listed runs are one with 42 events and a reported cost of 0.4213,
  one with 17 events and an estimated cost of 0.0136, and one with 17 events and no cost
- **THEN** the first line ends `42 events, $0.4213`, the second ends `17 events, ~$0.0136 estimated`, and the third
  ends `17 events`

#### Scenario: A run with notices and a cost
- **WHEN** a person runs `troupe status` and a listed run recorded 2 notices and reported a cost of 0.4213
- **THEN** its line ends `2 notices, $0.4213`

### Requirement: Logs show a run's tokens and cost on its result
Wherever troupe shows a run's `result` event as a line (`troupe logs`, with or without `--follow`, and `perform`'s
event lines), the line SHALL end with the tokens and cost the result carries, in brackets, an estimate marked with
`~` and `estimated` and a reported cost with `reported`. A result with neither SHALL show no brackets; one with only
one of them SHALL show only that one.

#### Scenario: A result with a reported cost
- **WHEN** a person runs `troupe logs <run>` for a run whose result is ok, with message `All 18 tests pass.`, the
  four counters 1204, 9817, 182330 and 14022, and `costUsd` 0.4213
- **THEN** the result line ends `result: ok: All 18 tests pass. (tokens 1,204 in, 9,817 out, 182,330 cache read,
  14,022 cache write; cost $0.4213, reported)`

#### Scenario: A result with an estimated cost
- **WHEN** a person runs `troupe logs <run>` for a run whose result is ok, with message `Reviewed 3 files.`, the
  counters 3410, 2066, 21504 and 0, and `estimatedCostUsd` 0.0136
- **THEN** the result line ends `result: ok: Reviewed 3 files. (tokens 3,410 in, 2,066 out, 21,504 cache read,
  0 cache write; cost ~$0.0136, estimated)`

#### Scenario: A result with neither
- **WHEN** a person runs `troupe logs <run>` for a run whose result carried no usage and no cost
- **THEN** the result line ends with the result's message, with nothing after it

#### Scenario: A result with tokens and no cost
- **WHEN** a person runs `troupe logs <run>` for a run whose result carried usage and no cost
- **THEN** the result line ends with the tokens in brackets and no cost

#### Scenario: The footer doesn't repeat them
- **WHEN** a person runs `troupe logs <run>` for a run whose result carried usage and a cost
- **THEN** the `run <id>: <outcome>` line after the events shows neither

### Requirement: A cost is shown to four decimal places, never as a false zero
troupe SHALL show a cost in US dollars to four decimal places. A non-zero cost that would show as `$0.0000` SHALL be
shown as `under $0.0001`, and an estimate as `~under $0.0001`. A cost reported or estimated as exactly 0 SHALL be
shown as `$0`. Token counts SHALL be shown with a comma between each group of three digits.

#### Scenario: A tiny estimate
- **WHEN** a person runs `troupe status <run>` for a run whose `cost` is 0.00003 `estimated`
- **THEN** the output shows `cost: ~under $0.0001, estimated from the runtime's price`

#### Scenario: A cost of exactly zero
- **WHEN** a person runs `troupe status <run>` for a run whose `cost` is 0 `reported`
- **THEN** the output shows `cost: $0, reported by the service`

#### Scenario: Rounding
- **WHEN** a person runs `troupe status <run>` for a run whose `cost` is 0.123456 `reported`
- **THEN** the output shows `cost: $0.1235, reported by the service`
