# Design

## Context

See proposal.md, Why. The relevant code:

- `plugins/runner-anthropic`: `reply.py`'s `Reply.prompt_tokens` is `input_tokens + cache_read_input_tokens +
  cache_creation_input_tokens`. Both guards use it: the shrinking prompt (`context.shrank`, compared in
  `loop.Loop._cut`) and the window (`context.against_window`, in `_cut` and after each reply in `Loop.run`). The
  compaction estimate calibrates bytes per token from it too (`Estimate.calibrate`). `loop.py`'s `_Spend.add` sums
  each reply's four counters as the API defines them. The budget is their total, and the result's `Usage` and
  `estimatedCostUsd` come from it. `runtime.py` is the one place the runner reads `run/start`'s runtime.
- Core: `troupe.core.runtimes` resolves a runtime's fields from `defaults.RUNTIMES`, then the theatre's config, then
  `TROUPE_RUNTIME_<NAME>_<FIELD>` (`FIELDS`, `PATTERNS`, `ACCEPTED`), each with its source. `Resolved.to_data` is the
  protocol's resolved runtime (`config get --resolved`, `Run.Started`'s `runtime`), and `RunRuntime.run_start` is
  `run/start`'s `runtime`. The last field added the same way was `prices` (change `estimated-cost`), and this change
  follows its path through the schemas, core, the SDK and the docs.
- The #415 probe (issuecomment-6865689324) recorded the accounting of both local engines: Ollama 0.40.14 reports
  `input_tokens` 30 with `cache_read_input_tokens` 374 (apart, as the API defines), and LM Studio reports 133 with 93
  for a prompt of about 133 tokens (inside). `fixtures/lm-studio-tool-loop` pins LM Studio's (126 with 89). Claude's
  API defines them apart in its documentation. Its fixtures report 0 cache reads. llama.cpp hasn't been probed.

anthropic-runner design D7 chose not to special-case engines. The owner's direction for #419 reverses that: fix the
accounting per engine, and don't guess when the engine is unknown.

## Goals / Non-Goals

**Goals:**
- The engine is named once, on the runtime, resolved like its other fields, and reaches the runner in `run/start`.
- One table in the runner holds each engine's accounting, as `context.SIGNALS` holds each engine's refusal.
- One function measures a reply's prompt, so both guards and the compaction estimate agree.
- Nothing about the engine is inferred from a reply or an endpoint.

**Non-Goals:**
- Other runners acting on the engine. They receive it and may ignore it.
- Catching Ollama's cut of a first request (D8's limit stands).
- A runner declaring which engines it supports, or config refusing an engine a runner can't use (#281's ground).
- Folding the context signals into the engine table. Signals stay matched against every engine, since a refusal is
  recognised by its own shape.

## Decisions

### D1. `engine` is a runtime field, resolved like the others

Owner, 2026-11-21: the engine belongs to the service, so it's a runtime field, not an actor option.

- **Schema.** `protocol/schemas/runtime.schema.json` gains `$defs/engine`, an enum of `claude`, `lm-studio`,
  `ollama` and `llama.cpp`, described as what serves the runtime's endpoint. Its resolved runtime gains `engine`
  (`{value, source}`). `config/runtime.schema.json` gains an optional `engine` referring to it, and
  `runner/run-start.schema.json`'s `runtime` an optional `engine`. Each copy under `packages/troupe/src/troupe/protocol/`
  changes with it.
- **Resolution.** `troupe.core.runtimes.FIELDS` gains `engine`, with its accepted words and pattern built from the one
  enum. So `TROUPE_RUNTIME_<NAME>_ENGINE` overrides config, which overrides the built-in, with source `env`, `theatre`
  or `default`. An empty variable is absent, and a value outside the set is `runtime.invalid-value`, naming the
  variable and the values (never the value, as for the other fields). Config refuses an unknown value through its
  schema check, naming the path and the values. Allowed on every runtime, the in-process one included: it describes
  the service, and a runner that doesn't use it ignores it.
- **Built-ins.** `anthropic` gets `engine` `claude` (owner: "api.anthropic.com's built-in runtime counts as claude").
  `ollama` gets `ollama`, which is what serves that endpoint, so the Anthropic runner pointed at a copy of it counts
  correctly. `openai` and `mistralrs` get none: neither is in the set.
- **Hand-off.** `Resolved` carries `engine: Sourced | None`. `to_data` and `RunRuntime.to_data` show it with its
  source, and `run_start` sends its value when present, never a null. The SDK's `RuntimeParams` gains
  `engine: str | None`, checked against the same set, so a runner refuses a `run/start` with a value it can't name
  (a protocol error naming `runtime.engine`).
- **Version.** Each field is optional, and a troupe from before this change sends none. It ships as a
  `feat(protocol)` commit, and release-please sets the version. A runner built against an older protocol, whose own
  schema check rejects unknown keys in `runtime`, would refuse a `run/start` carrying `engine`. Every runner in this
  repository parses through the SDK, which this change updates. That risk is the same one `price` took, and it's
  pre-1.0.

*Alternatives:* an actor option on the Anthropic runner (the first draft's A). It's contained, but it puts a property
of the service on each actor. Probing the engine's own REST endpoints. That's an extra request outside the library,
and ambiguous behind a proxy. Sniffing headers or ids was rejected outright: it's guessing.

### D2. An engine table in the runner

`context.py` gains `Engine` (the runtime's value, a display name, whether `input_tokens` includes cache reads, which
is `True`, `False` or `None` for not known, and what pins it) and `ENGINES`, one entry per value in the protocol's
set. A test checks the table's values equal the schema's enum, so a value added to the protocol can't reach the
runner without an entry. llama.cpp's accounting is `None` until a probe or fixture pins it. `Signal.engine` display
names and `Engine.name` are the same strings, and a test checks that too.

*Alternative:* a separate `engines.py`. That splits engine knowledge across two modules the README would both have to
name. `context.py` is small, so one module stays readable.

### D3. One prompt measure, two readings when the accounting isn't known

`context.prompt_readings(usage, includes_reads) -> tuple[int, ...] | None`:

- apart (`False`): `(input + read + write,)`
- inside (`True`): `(input + write,)`
- not known (`None`, from no engine or llama.cpp): `(input + write, input + read + write)`, both readings
- `input_tokens` not a count: `None` (unchanged: no guard can judge it)

`shrank(previous, current)` becomes true when **any** reading of the current reply is smaller than the same reading
of the previous accepted reply. The previous readings are stored as a tuple. With a known accounting it's the old
single comparison. When the accounting isn't known it fails on either, which is the conservative side #279 asks for.
The cost is a false `context-length` only on such an engine when its cache reads grow faster than its prompt, and the
warning (D5) points at the fix.

The window guard and the compaction estimate take the **largest** reading. For the window, the larger reading reaches
it sooner (the safe side). For the estimate, a larger token count gives fewer bytes per token, so compaction removes
more, not less.

*Alternative:* treat an unknown engine as the API defines it (status quo). That keeps today's miss on LM Studio
whenever nobody named the engine, which is the silent loss this change fixes.

### D4. Usage counted once

`_Spend.add` takes the accounting. On an inside-counting engine it adds `max(input - read, 0)` to `input_tokens`. A
negative difference would mean the engine changed its accounting, so it's clamped rather than raised, and the reply's
own counters stay in the transcript. Cache reads are still added as `cacheReadTokens`. So `inputTokens +
cacheReadTokens` is the prompt, and the budget and the estimated cost count each token once. When the accounting isn't
known, usage stays as the API defines it: no correction without knowing it's due.

### D5. The warning when the accounting isn't known

The first reply with `cache_read_input_tokens > 0` sends one `log` (level `warning`) when the accounting isn't known.
With no engine, it says the usage may count those tokens twice (LM Studio does), and that the runtime's `engine` field
corrects it, naming the runtime. On llama.cpp, it says troupe doesn't yet know how that engine counts them. It goes
only where the ambiguity changes a number, so runs on fake endpoints and engines without cache reads stay as they are.

### D6. Fixtures name their engine

The replay hands the runner a `run/start` it builds itself. Each fixture's `provenance.json` gains `engine` (`claude`
for the `claude-*` fixtures, `lm-studio` for the `lm-studio-*`), and the replay puts it in `run/start`'s runtime.
The LM Studio fixtures' expected usage changes to the corrected count (`lm-studio-tool-loop`: `inputTokens` 219 →
130; `lm-studio-output-limit`: 43 → 28; `lm-studio-conversation-cut`: recomputed). A fixture test checks every
fixture names an engine from the table. The cut with cache reads is a new derived fixture,
`lm-studio-conversation-cut-cached`, from the recorded fixture's replies 0, 1 and 4, with its provenance saying so. It
replays through the real process like the others.

## Risks / Trade-offs

- [A runtime names the wrong engine] → `lm-studio` on an engine that reports apart under-counts input and measures
  the prompt short, so a growing conversation could look shrunk and fail loudly. It can't hide a cut. The runtimes
  page says to name the engine actually serving.
- [LM Studio fixes its accounting (#419's upstream fix)] → `lm-studio` would then under-count. #419's to-do already
  re-records the fixture when that happens. The table entry then changes, or names the version range.
- [Unknown engine, false `context-length`] → only when cache reads grow faster than the prompt on an engine nobody
  named. The run fails loudly, the warning names the fix, and the person sets the runtime's `engine`.
- [A third-party runner with a strict schema check] → it refuses a `run/start` carrying `engine` until it updates
  (D1, Version). That's accepted pre-1.0, and troupe sends the field only when a runtime names an engine.

## Migration Plan

None: the field is new and optional, and no records exist pre-1.0. A run on a runtime without `engine` behaves as
before, except that the shrinking-prompt guard also fails on a shrinking input alone (D3), and the warning (D5)
appears. A run on the built-in `anthropic` runtime is now counted as Claude's API, which is how it was counted anyway.
