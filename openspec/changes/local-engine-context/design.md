# Design

## Context

See proposal.md, Why. The relevant code in `plugins/runner-anthropic`:

- `reply.py`'s `Reply.prompt_tokens` is `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. Both
  guards use it: the shrinking prompt (`context.shrank`, compared in `loop.Loop._cut`) and the window
  (`context.against_window`, in `_cut` and after each reply in `Loop.run`). The compaction estimate calibrates bytes
  per token from it too (`Estimate.calibrate`).
- `loop.py`'s `_Spend.add` sums each reply's four counters as the API defines them. The budget is their total, and the
  result's `Usage` and `estimatedCostUsd` (through the SDK's estimator) come from it.
- `options.py` checks a closed set of options against the published `options.schema.json`. A test compares the two on
  generated options.
- The #415 probe (issuecomment-6865689324) recorded the accounting of both local engines: Ollama 0.40.14 reports
  `input_tokens` 30 with `cache_read_input_tokens` 374 (apart, as the API defines), and LM Studio reports 133 with 93
  for a prompt of about 133 tokens (inside). `fixtures/lm-studio-tool-loop` pins LM Studio's (126 with 89). Claude's
  API defines them apart. Its fixtures report 0 cache reads, so its entry is pinned by the API's documentation.

anthropic-runner design D7 chose not to special-case engines. The owner's direction for #419 reverses that: fix the
accounting per engine, and don't guess when the engine is unknown.

## Goals / Non-Goals

**Goals:**
- One table holds each engine's accounting, as `context.SIGNALS` holds each engine's refusal.
- One function measures a reply's prompt, so both guards and the compaction estimate agree.
- Nothing about the engine is inferred from a reply.

**Non-Goals:**
- Catching Ollama's cut of a first request (D8's limit stands).
- Folding the context signals into the engine table. Signals stay matched against every engine, since a refusal is
  recognised by its own shape and catching one costs nothing when the engine is unknown.

## Decisions

### D1. An engine table beside the signal table

`context.py` gains `Engine` (its option value, display name, whether `input_tokens` includes cache reads, and what pins
it) and `ENGINES`, one entry each for `claude`, `lm-studio`, `ollama` and `llama.cpp`. llama.cpp's is taken from its
server's documentation, marked so until a probe or fixture confirms it, like its signal entry. `context.py` stays the
single place the README points to for "how each engine behaves". The `Signal.engine` display names and
`Engine.name` are the same strings.

*Alternative:* a separate `engines.py`. That splits engine knowledge across two modules the README would both have to
name. `context.py` is small (113 lines), so one module stays readable.

### D2. How the runner learns the engine (with the owner)

**Assumed: option A, an actor option `engine`.** It's a closed enum checked in `options.py` and published in
`options.schema.json`. An unknown or differently-spelled value is `anthropic.invalid-options`, never "unknown engine"
(malformed input is an error, not a fall-through). The built-in runtime's endpoint `https://api.anthropic.com` (by
scheme and host, any path) means `claude` when the option is absent. When the option is present it wins, so a gateway
in front of Claude can say `claude`.

*Alternatives:* **B**, a field on the runtime (troupe's config, #278). That's where the engine belongs, since it's a
property of the service rather than the actor, but it touches core config, `run/start` in the protocol, and every
runner's view of a runtime. **C**, probing the engine's own REST endpoints (LM Studio's `/api/v0/models`, Ollama's
`/api/version`). That's an extra request outside the `anthropic` library, against endpoints the runner otherwise never
touches, and an answer from both, or a proxy, is ambiguous. Sniffing headers or message ids was rejected outright:
it's guessing.

If the owner picks B, D3 to D5 stand unchanged. Only where `Engine` comes from moves, from `parse_options` to the
runtime parse, and tasks 2.x change accordingly.

### D3. One prompt measure, two readings when unknown

`context.prompt_readings(usage, engine) -> tuple[int, ...] | None`:

- engine reports apart: `(input + read + write,)`
- engine reports inside: `(input + write,)`
- unknown: `(input + write, input + read + write)`, both readings
- `input_tokens` not a count: `None` (unchanged: no guard can judge it)

`shrank(previous, current)` becomes true when **any** reading of the current reply is smaller than the same reading
of the previous accepted reply. The previous readings are stored as a tuple, not one number. With a known engine it's
the old single comparison. With the engine unknown it fails on either. That's the conservative side #279 asks for, and
the cost is a false `context-length` only on an unnamed engine whose cache reads grow faster than its prompt, which
the `log` warning (D5) points at.

The window guard and the compaction estimate take the **largest** reading. For the window, the larger reading reaches
it sooner (the safe side). For the estimate, the larger token count gives fewer bytes per token, so compaction removes
more, not less. With a known engine there's one reading, so nothing changes for it.

*Alternative:* treat the unknown engine as the API defines it (status quo) for the guard. That keeps today's miss on
LM Studio whenever the person hasn't named it, which is the silent loss this change exists to fix.

### D4. Usage counted once

`_Spend.add` takes the engine. On an inside-counting engine it adds `max(input - read, 0)` to `input_tokens`. A
negative difference would mean the engine changed its accounting, so it's clamped rather than raised, and the reply's
own counters stay in the transcript. Cache reads are still added as `cacheReadTokens`. So `inputTokens +
cacheReadTokens` is the prompt, and the budget and the estimated cost count each token once. With the engine unknown,
usage stays as the API defines it: no correction is applied without knowing it's needed.

### D5. The warning on an unknown engine

The first reply with `cache_read_input_tokens > 0` on an unknown engine sends one `log` (level `warning`): the usage
may count those tokens twice (LM Studio does), and setting `engine` corrects it. It goes only where the ambiguity
changes a number, so runs on fake endpoints and engines without cache reads stay as they are.

### D6. Fixtures name their engine

Each fixture's `provenance.json` gains `options.engine` for the engine it was recorded from or modelled on (`claude`
for the `claude-*` fixtures, `lm-studio` for the `lm-studio-*`), which the replay already merges into the run's
options. The LM Studio fixtures' expected usage changes to the corrected count (`lm-studio-tool-loop`: `inputTokens`
219 → 130; `lm-studio-output-limit`: 43 → 28; `lm-studio-conversation-cut`: recomputed). A fixture test checks every
fixture names an engine from the table. The cut with cache reads is a new derived fixture,
`lm-studio-conversation-cut-cached`, made from the recorded fixture's replies 0, 1 and 4, its provenance saying so,
so it replays through the real process like the others.

## Risks / Trade-offs

- [The person names the wrong engine] → `engine` `lm-studio` on an engine that reports apart under-counts input and
  measures the prompt short, so a growing conversation could look shrunk and fail loudly. It can't hide a cut. The
  README says to set it to the engine actually serving.
- [LM Studio fixes its accounting (#419's upstream fix)] → `engine` `lm-studio` would then under-count. #419's to-do
  already re-records the fixture when LM Studio fixes it. The table entry then changes, or names the version range.
- [Unknown engine, false `context-length`] → only when cache reads grow faster than the prompt on an engine nobody
  named. The run fails loudly, the warning names the fix, and the person sets `engine`.
- [Option A puts a property of the service on the actor] → two actors on one runtime each say `engine`. That's
  accepted for containment, and B remains open (D2).

## Migration Plan

None: the option is new and optional. No records exist pre-1.0. A run without `engine` behaves as before, except that
the shrinking-prompt guard now also fails on a shrinking input alone (D3), and the warning (D5) appears.
