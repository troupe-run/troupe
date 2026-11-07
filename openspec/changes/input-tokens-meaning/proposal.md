# Proposal: what usage.inputTokens counts

Issue: [troupe#293](https://github.com/troupe-run/troupe/issues/293). Found building the OpenAI runner
([troupe#162](https://github.com/troupe-run/troupe/issues/162), its design D9 and D12 gap 3).

## Why

A run's `result.usage` has four counters, and the runner contract says what three of them mean. `inputTokens` is only
"input tokens the engine used", and the engines disagree on that. Anthropic's `input_tokens`, which the Claude Code
runner maps straight to `inputTokens`, leaves out the tokens read from and written to the prompt cache. OpenAI's
`input_tokens` includes them. The OpenAI runner subtracts to match Claude Code, and the Ollama runner's
`prompt_eval_count` already leaves cached tokens out. So the three runners troupe ships agree, but by convention
between runners, not by the contract. A runner written outside this repository could read the schema, report OpenAI's
total as `inputTokens` beside `cacheReadTokens`, and count the cached tokens twice in anything that adds the counters
up. The contract is still a draft (version 0), so this is the cheap time to say it.

## What Changes

- **The contract says what `inputTokens` counts:** the input tokens not counted in `cacheReadTokens` or
  `cacheWriteTokens`, so the three add up to the run's whole input. `run-event.schema.json`'s `usage` descriptions say
  so, in `protocol/schemas/runner/` and the copy troupe carries.
- **It says what a missing cache counter means:** the runner couldn't report it. Input the engine counted that the
  runner couldn't separate into a cache counter stays in `inputTokens`. A runner never estimates a counter. (The OpenAI
  runner already works this way when only some responses report cache writes.)
- **`contributing/runners.md` says the same**, in the run events table and in a short "What usage counts" note, and
  each shipped runner's mapping says how it meets it.
- **Each runner troupe ships is checked against it:** Claude Code (Anthropic's count already excludes the cache) meets
  it. The OpenAI runner subtracts both, but reports `cacheReadTokens` 0 when the service never said how many tokens it
  served from its cache, reading "not reported" as "none". Fixing that is a runner behaviour change, so it's
  [troupe#304](https://github.com/troupe-run/troupe/issues/304), not this change; the services it speaks to today
  (OpenAI, local Ollama) report cached tokens on every response, so no run seen so far is affected.
  Ollama's `inputTokens` has the right meaning, but the tokens Ollama served from its cache aren't reported yet, so its three counters add up to less than the whole input until
  [troupe#282](https://github.com/troupe-run/troupe/issues/282) reports them as `cacheReadTokens`. That stays #282's
  work; its README and mapping say so.
- **A test pins the descriptions**, so the counter can't drift back to a vague meaning unnoticed.
- No shape change: the same four optional counters, the same validation, and the runner contract stays version 0. It
  is released as a protocol fix (a `fix(runner-protocol)` commit that changes `protocol/`), which releases the protocol
  and `troupe`, whose copy of the schema changes too.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runner-protocol`: the result event's requirement says what each usage counter counts, that the input counters add
  up to the whole input, and what a missing cache counter means.

## Impact

- `protocol/schemas/runner/run-event.schema.json` and `packages/troupe/src/troupe/protocol/runner/run-event.schema.json`:
  descriptions of `usage` and its counters.
- `contributing/runners.md`: the `result` row, a note on what usage counts, and the Claude Code and Ollama mapping rows.
- `packages/troupe-plugin-sdk/src/troupe_plugin_sdk/runner.py`: the `Usage` docstring, so a Python runner's author sees
  the meaning where they set it.
- `plugins/runner-ollama/README.md`: names the gap #282 closes in the contract's terms.
- `packages/troupe/tests/test_runner_schemas.py`: the test that pins the descriptions.
- No runner's behaviour changes, and runs already recorded need nothing: the three runners' `inputTokens` has had this
  meaning since they were built. The OpenAI runner's unreported cache reads are #304, Ollama's are #282.
- No spec Purpose changes, so no infrastructure `oob/troupe-spec-purposes.json` update.
