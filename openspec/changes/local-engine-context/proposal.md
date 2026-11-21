# Proposal

## Why

The Anthropic runner (#415) adds every reply's `input_tokens` and cache counters as the Messages API defines them. LM
Studio counts its cache reads inside `input_tokens` as well (#419), and the same sum is the context guard's measure of
a reply's prompt (#418, design D8). So on LM Studio the guard double-counts the cache reads, and a cut on a turn that
reports cache reads goes unnoticed. `lm-studio-conversation-cut`'s own replies show it: the cut reply 2 reports no
cache reads and is caught, but replies 4 to 6 come from the same cut conversation and report 4,037 input and 3,840
cache-read tokens. The guard reads that as a prompt of 7,877, more than the 4,597 before it. Replayed with reply 4 in
place of reply 2, the runner on main acts on the cut reply and sends a fourth request. It's the silent loss #279 rules
out, and the run's usage, budget and estimated cost are over-stated by every cache read.

## What Changes

- **Each engine's usage accounting, in one table.** The runner knows, per engine, whether `input_tokens` includes
  cache reads: Claude's API and Ollama report them apart, LM Studio inside, and llama.cpp from its documentation until
  it's probed. Each entry names the fixture or the probe that pins it, as the context-signal table's entries do.
- **The runner is told the engine; it doesn't guess.** Nothing in a reply names the engine. A new option, `engine`,
  names it from a closed set (`claude`, `lm-studio`, `ollama`, `llama.cpp`). An unknown value is refused
  (`anthropic.invalid-options`). The built-in runtime's endpoint, `https://api.anthropic.com`, is Claude's API without
  it. *How the engine is named is with the owner (design D2); option A is recommended and assumed here.*
- **Usage follows the engine.** On LM Studio, `inputTokens` is `input_tokens` less `cache_read_input_tokens`, so the
  result, the token budget and the estimated cost count each token once. With the engine unknown, usage stays as the
  API defines it, and the first reply that reports cache reads brings a `log` warning, once, saying the count may hold
  them twice and naming the `engine` option.
- **The guard measures the prompt per engine.** A reply's prompt is `input_tokens` plus the cache counters on an
  engine that reports them apart, and `input_tokens` plus cache writes on LM Studio. With the engine unknown, the
  guard takes a prompt as shrunk if either reading shrank, which is the conservative side (#279: fail by default).
  The `contextWindow` guard uses the same measure.
- **The README says which engines can still lose content silently** (#418's done-when): Ollama, on a first request
  already over its window, and any engine the runner hasn't been told about, mid-run, only as far as both readings
  allow. LM Studio and Claude's API refuse a first request that's over the window. Its note on #419 changes from "the
  runner doesn't special-case engines" to how the `engine` option corrects it.
- **Tests that fail on main**: the cut replayed with reply 4 (cache reads reported) ends `context-length` without
  acting on the reply, and `lm-studio-tool-loop` with `engine` `lm-studio` reports `inputTokens` 130 (93 + 126 − 89).
  Each fixture's provenance names the engine it was recorded from, so the LM Studio fixtures' expected usage changes
  to the corrected count.

Not in scope: catching Ollama's cut of a first request (D8's limit stands: no earlier prompt to compare with, and no
tokenizer); reporting the bugs upstream (the owner kept them as troupe's own, 2026-11-14); dropping the guard for an
engine that starts refusing (#418's watch item, for when one does).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `anthropic-runner`: the closed options gain `engine`; usage is summed per engine; the shrinking-prompt and window
  guards measure a reply's prompt per engine, conservatively when the engine is unknown; the README names the engines
  that can still lose content silently.

## Impact

- `plugins/runner-anthropic`: `context.py` (or a new `engines.py`) holds the engine table and the prompt measure;
  `reply.py`'s `prompt_tokens`, `loop.py`'s `_Spend` and guard, `options.py` and `schemas/options.schema.json` (the
  `engine` option), the README, and tests (`test_anthropic_context.py`, `test_anthropic_loop.py`,
  `test_anthropic_options.py`, `test_anthropic_fixtures.py`).
- No protocol, core or other runner changes under option A. Option B (a runtime field) would touch troupe's runtime
  config and the runner protocol's `run/start`.
- Fixes #419 (the runner corrects LM Studio's count when told the engine) and #418 (the guard holds on LM Studio's
  accounting, and the README names the engines that can still cut silently).
