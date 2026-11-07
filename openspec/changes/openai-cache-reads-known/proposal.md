# Proposal: the OpenAI runner reports cache reads only when every response reports them

Issue: [troupe#304](https://github.com/troupe-run/troupe/issues/304). Found checking each shipped runner against
[troupe#293](https://github.com/troupe-run/troupe/issues/293)'s wording for `usage` (the `input-tokens-meaning`
change).

## Why

The OpenAI runner's `_Spend.add` takes a response without a readable `input_tokens_details.cached_tokens` as 0 tokens
read. So a service that never says how many tokens it served from its cache gets `cacheReadTokens` 0, which reads as
"none were read" when the answer is "not reported". #293's contract wording says a cache counter that's left out
wasn't reported, and that a runner never estimates one: input the runner can't separate into a cache counter stays in
`inputTokens`. The runner already treats cache writes that way (#162's design D9, "when every response reports it"),
but D9 didn't decide reads. This change makes reads match writes, so the runner meets the contract #293 states.

## What Changes

- **Cache reads are known only when every response reports them.** The runner tracks whether every response's usage
  gave a readable `cached_tokens`, beside the flag it already keeps for `cache_write_tokens`. While that holds, the
  result's `cacheReadTokens` is the sum and `inputTokens` has it subtracted, as today. Once any response leaves it out
  (or gives a value that isn't a whole number of tokens), the result has no `cacheReadTokens` and `inputTokens`
  keeps the reads the other responses reported.
- **Reads and writes are decided apart.** A run whose responses all report writes but not all reads still reports
  `cacheWriteTokens` and subtracts it, and the other way round.
- **Both partial cases get tests:** writes reported by only one of two responses, and cached tokens reported by only
  one of two. Neither has a test today.
- **The openai-runner spec's "Usage is summed into the result" requirement** says both cache counters are reported
  only when every response reports them, with scenarios for the two partial cases.
- **The runner's README** (its usage paragraph) and **the Responses API mapping row in `contributing/runners.md`** say
  the same.
- Runs already recorded replay unchanged: OpenAI and local Ollama report `cached_tokens` on every response, as every
  fixture in `plugins/runner-openai/fixtures/responses/` shows. Only a service that leaves it out sees a difference,
  and there the result stops claiming 0 reads.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openai-runner`: "Usage is summed into the result" reports `cacheReadTokens`, like `cacheWriteTokens`, only when
  every response reports it, and keeps unreported reads in `inputTokens`.

## Impact

- `plugins/runner-openai/src/troupe_runner_openai/loop.py`: `_Spend` (a `reads_known` flag beside `writes_known`;
  `add` and `usage`).
- `plugins/runner-openai/tests/test_openai_loop.py`: tests for the two partial cases, and for reads and writes being
  decided apart.
- `openspec/specs/openai-runner/spec.md`: the usage requirement and its scenarios (through this change's delta).
- `plugins/runner-openai/README.md` and `contributing/runners.md`: the usage wording.
- Depends on #293 for the contract's wording. It doesn't change the contract or its schema, and its code doesn't need
  #293's text to land first, but its docs cite that wording, so the pull request follows #293's (see design D4).
- Out of scope: the contract's wording itself (#293) and the Ollama runner's cache reads (#282).
- No spec Purpose changes, so no infrastructure `oob/troupe-spec-purposes.json` update.
