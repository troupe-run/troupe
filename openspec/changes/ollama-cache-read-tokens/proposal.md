# Proposal

## Why

The Ollama runner's `result` doesn't report the prompt tokens Ollama served from its cache, and its `inputTokens`
counts them anyway. Each answer's last line has `prompt_eval_count` and `prompt_eval_cached_count`, and the first
includes the second. Checked on 2026-11-07 against Ollama 0.40.14: the same 78-token prompt sent twice reported
`prompt_eval_count` 78 both times, with `prompt_eval_cached_count` 0 and then 77. The committed fixtures agree: a
second request reports 1276 with 1218 cached, and took a tenth of the first request's evaluation time.

troupe#293 settles what `inputTokens` means for every runner: the input tokens not read from or written to a cache,
so the total input is `inputTokens + cacheReadTokens + cacheWriteTokens`. The Claude Code runner already reports it
that way (Anthropic's own split), and the OpenAI runner subtracts to match. The Ollama runner is the one runner that
doesn't, so a run on Ollama overstates the input it used next to one on either of the others. Closes troupe#282.

## What Changes

- Each answer's `prompt_eval_cached_count` is summed over the run into `result.usage.cacheReadTokens`. It's left out
  when no answer reported it, as the other counters are.
- `usage.inputTokens` becomes the sum of each answer's `prompt_eval_count` less its `prompt_eval_cached_count`,
  troupe#293's meaning. This changes the value a run reports whenever Ollama took tokens from its cache. Nothing in
  troupe reads `usage` to make a decision yet, so no reader breaks, but anyone comparing runs from before and after
  will see `inputTokens` fall by the cached amount, which now appears as `cacheReadTokens`.
- The README's run-events section says the wrong thing today: it says the cached tokens "aren't in `inputTokens`".
  It and `contributing/runners.md`'s Ollama table are corrected.
- The captured fixtures' expected `result` events are updated to the new usage. Their recorded exchanges already
  carry `prompt_eval_cached_count`, so no re-capture is needed.
- `cacheWriteTokens` stays absent: Ollama reports nothing that maps to it.
- Not in scope: the contract text itself (`run-event.schema.json`'s `usage` descriptions and the contract's section
  of `contributing/runners.md`). That's troupe#293's own protocol change. This change follows the meaning #293 sets
  and doesn't wait for it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `ollama-runner`: "The result carries the run's counts" now says how `prompt_eval_cached_count` becomes
  `cacheReadTokens`, and that `inputTokens` leaves the cached tokens out.

## Impact

- `plugins/runner-ollama/src/troupe_runner_ollama/conversation.py`: reads `prompt_eval_cached_count` from an
  answer's last line, sums it, and subtracts it from the input count.
- `plugins/runner-ollama/tests/`: unit and property tests for the new counter, and the fake endpoint's `done()`
  helper takes a cached count.
- `plugins/runner-ollama/fixtures/ollama/*/events.json`: the `result` usage of the five fixtures whose answers have
  counts. Their `provenance.json` notes the update.
- `plugins/runner-ollama/README.md` and `contributing/runners.md`: the usage mapping.
- No protocol, schema, SDK or core change. The `Usage` model already has `cache_read_tokens`.
