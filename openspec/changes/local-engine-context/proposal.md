# Proposal

## Why

The Anthropic runner (#415) adds every reply's `input_tokens` and cache counters as the Messages API defines them. LM
Studio counts its cache reads inside `input_tokens` as well (#419), and the same sum is the context guard's measure of
a reply's prompt (#418, anthropic-runner design D8). So on LM Studio the guard double-counts the cache reads, and a
cut on a turn that reports cache reads goes unnoticed. `lm-studio-conversation-cut`'s own replies show it: the cut
reply 2 reports no cache reads and is caught, but replies 4 to 6 come from the same cut conversation and report 4,037
input and 3,840 cache-read tokens. The guard reads that as a prompt of 7,877, more than the 4,597 before it. Replayed
with reply 4 in place of reply 2, the runner on main acts on the cut reply and sends a fourth request. It's the silent
loss #279 rules out, and the run's usage, budget and estimated cost are over-stated by every cache read.

Nothing in a reply says which engine sent it, so the runner has to be told. The engine is a property of the service,
so it belongs on the runtime, beside its endpoint and model (owner, 2026-11-21).

## What Changes

- **A runtime can name its engine.** Runtime config gains `engine`, one of a closed set: `claude`, `lm-studio`,
  `ollama` and `llama.cpp`. An unknown value is refused, naming the field and the values it takes.
  `TROUPE_RUNTIME_<NAME>_ENGINE` overrides it like the runtime's other fields, and a malformed value there is
  `runtime.invalid-value`. The built-in `anthropic` runtime's engine is `claude`, and the built-in `ollama`'s is
  `ollama`. A runtime with no engine has an unknown one.
- **troupe passes it on.** The resolved runtime (`troupe config get --resolved`, the run's start) shows the engine with
  its source, and `run/start`'s `runtime` carries `engine` when the runtime has one. The protocol gains an optional
  field in each of the runtime config, the resolved runtime and `run/start`. It's not **BREAKING**: a runner that
  doesn't use it ignores it.
- **The plugin SDK** parses `runtime.engine` into `RunStartParams`, refusing a value outside the set.
- **The Anthropic runner counts and guards per engine**, from one table that says, for each engine, whether
  `input_tokens` includes cache reads. Claude's API and Ollama report them apart, and LM Studio inside. llama.cpp's
  accounting hasn't been probed, so its entry says unknown, and a run on it is counted and guarded as on an unknown
  engine. Each entry names what pins it.
  - Usage: on LM Studio, `inputTokens` is `input_tokens` less `cache_read_input_tokens`, so the result, the token
    budget and the estimated cost count each token once.
  - The guards: a reply's prompt is `input_tokens` plus the cache counters on an engine that reports them apart, and
    `input_tokens` plus cache writes on LM Studio. The `contextWindow` guard uses the same measure.
  - **An unknown engine runs conservatively** (owner, 2026-11-21): usage as the API defines it, one `log` warning
    naming the runtime's `engine` field the first time a reply reports cache reads, and a prompt taken as cut if it
    shrank under either reading.
- **The README says which engines can still lose content silently** (#418's done-when): Ollama, on a first request
  already over its window. On a runtime with no engine, a mid-run cut is still caught under both readings. LM Studio
  and Claude's API refuse a first request that's over the window. Its note on #419 changes to how the runtime's
  `engine` corrects the count.
- **Tests that fail on main**: the cut replayed with reply 4 (cache reads reported) ends `context-length` without
  acting on the reply, on LM Studio and with the engine unknown. `lm-studio-tool-loop` on an `lm-studio` runtime
  reports `inputTokens` 130 (93 + 126 − 89). Each fixture's provenance names its engine, so the LM Studio fixtures'
  expected usage changes to the corrected count.

Not in scope: catching Ollama's cut of a first request (D8's limit stands: no earlier prompt to compare with, and no
tokenizer); other runners using the engine (they may ignore it); components declaring what they require of a runtime
(#281); reporting the bugs upstream (the owner kept them as troupe's own, 2026-11-14); dropping the guard for an
engine that starts refusing (#418's watch item).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runtimes`: a runtime's `engine` field, its environment override and the refusal of a malformed one, the built-ins'
  engines, and `config get --resolved` showing it.
- `runner-protocol`: `run/start`'s `runtime` carries `engine`.
- `runs`: the run's start records the runtime's engine with its source.
- `plugin-sdk`: `RunStartParams` parses `runtime.engine`.
- `anthropic-runner`: usage summed per engine; the shrinking-prompt and window guards measure a reply's prompt per
  engine, conservatively when it's unknown; one warning for an unknown engine's cache reads; the README names the
  engines that can still lose content silently.

## Impact

- Protocol: `protocol/schemas/runtime.schema.json` (`$defs/engine`, `resolved.engine`),
  `protocol/schemas/config/runtime.schema.json` (`engine`), `protocol/schemas/runner/run-start.schema.json`
  (`runtime.engine`), and their copies under `packages/troupe/src/troupe/protocol/`. It ships as a `feat(protocol)`
  commit, and release-please versions it. Every field is optional, so it's not breaking.
- Core: `troupe.core.defaults` (the built-ins' engines), `troupe.core.runtimes` (resolving `engine`, the environment
  override, `Resolved`/`RunRuntime` data), the config model and its error wording, and the CLI's resolved-runtime view
  if it lists fields.
- `packages/troupe-plugin-sdk` (`RunStartRuntime.engine`, `RuntimeEngine`, `RUNTIME_ENGINES`).
- `plugins/runner-anthropic`: `context.py` (the engine table, the prompt measure), `reply.py`, `loop.py`,
  `runtime.py`, fixtures and tests.
- Docs: `docs/stagecraft/runtimes.md`, `contributing/runners.md`, `docs/prompt-book/config-schema.md` (generated),
  `plugins/runner-anthropic/README.md`, and the scripted runner's README if it lists `run/start`'s runtime.
- No spec Purpose changes, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json` is untouched.
- Fixes #419 (the runner corrects LM Studio's count on an `lm-studio` runtime) and #418 (the guard holds on LM
  Studio's accounting, and the README names the engines that can still cut silently).
