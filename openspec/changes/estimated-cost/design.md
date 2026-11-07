# Design: a cost estimated from a price, marked as one

## Context

See proposal.md for why. What the code does today:

- `result.costUsd` (`protocol/schemas/runner/run-event.schema.json`, copied to `packages/troupe/src/troupe/protocol/`)
  is "as the engine reports it". The SDK's `ResultEvent.cost_usd` mirrors it. Core never reads it: the host checks
  the result against the schema and records it, and no surface shows it.
- The Claude Code runner maps `total_cost_usd`. The Ollama runner carries no cost, and takes no runtime from
  `run/start`. The OpenAI runner's `_Spend` (`plugins/runner-openai/src/troupe_runner_openai/loop.py`) sums a `cost`
  from each response's usage when every response has one, rounded to 10 places, and otherwise leaves it out.
- A runtime is resolved in `troupe.core.runtimes` from defaults, the theatre's config and the environment, each value
  with its source. `perform` builds `run/start`'s `runtime` from `runtime.run_start()`, and records the resolved form
  (`protocol/schemas/runtime.schema.json#/$defs/resolved`) in `Run.Started`, the rehearsal and `config get
  --resolved`.
- `troupe config set` splits a path at every dot (`troupe.cli.values.split_path`), with no quoting.

## Goals / Non-Goals

**Goals:**
- One unmistakable field for an estimate, and a rule that makes it absent rather than wrong.
- A price set once, in config, recorded with each run that used it, so any estimate can be checked again from the
  event store alone.

**Non-Goals:**
- Changing what `usage.inputTokens` counts (#293). The estimate relies on the runners' current convention: input tokens
  exclude cache reads and writes, so each counter is priced once.
- Tiered or long-context prices, batch discounts, reasoning tokens priced apart from output. A price is four flat
  rates. A service whose billing doesn't fit leaves the price unset.
- Addressing a model's name containing a dot in a `config set` path (D5).

## Decisions

### D1. `estimatedCostUsd`, a field of its own, not `costUsd` plus `costSource`

The issue offers `costUsd` plus `costSource: reported | estimated`. Rejected: every reader would have to check two
fields, and one that reads only `costUsd` (any consumer written for version 0's meaning, a quick `jq`, a later sum
across runs) would take an estimate for a reported cost, which is the confusion the issue is about. With a field of
its own, a reader that knows nothing of estimates sees no cost. That's the outcome that can't mislead. `costUsd` keeps
its meaning, and the change is purely additive.

Also rejected: a `cost` object (`{usd, source}`), which would replace `costUsd` and break every runner and recording
for no gain over D1.

### D2. A result carries one or the other, never both

The schema forbids both together (`not: {required: [costUsd, estimatedCostUsd]}`). A runner estimates only when the
service reported no cost. Carrying both would invite a reader to pick one, and checking a price against reported costs
is a job for a later tool, not the result.

### D3. The price comes from troupe, in `run/start`, one price per run

Rejected: a runner's own built-in table, which goes stale silently and would be a guess troupe can't see; a table
troupe publishes, for the same reason plus an update channel (out of scope in the issue). So config is the only
source, and troupe has no built-in prices (`defaults.RUNTIMES` gains none).

troupe resolves the run's price and sends only that, as `runtime.price`, not the table. The runner needs nothing else,
and `run/start` stays small. `RunStartRuntime` in the SDK gains `price: Price | None`.

### D4. A price is four rates in US dollars per million tokens, named after the counters

`{"input", "output", "cacheRead", "cacheWrite"}`: the usage counters' names without `Tokens`, so the pairing is
plain, and per million because that's how services publish prices, so a person types what they read. `input` and
`output` are required: a price without them isn't one. The cache rates are optional, because not every service has
them. The object is closed. Each rate is a JSON number of zero or more, and schema validation refuses NaN and
infinities as it does everywhere (strict JSON).

The price definition lives once, in `protocol/schemas/runtime.schema.json#/$defs/price`. The config file, `run/start`
and the resolved runtime all `$ref` it.

### D5. Config: `runtimes.<name>.prices`, a map keyed by the model's name

A price belongs to a model at a service, and the run's model can come from the environment, the actor or the runtime
(spec: runtimes). So it's keyed by model on the runtime, not set on the actor (an environment model override would
leave the actor's price wrong) and not one price per runtime (wrong as soon as an actor picks another model). Keys
are checked with the existing model-name definition (`propertyNames`).

**The dotted-path limit** (also raised by a side agent while this was written): `config set` splits at dots, so
`runtimes.openai.prices.gpt-4.1` can't address `gpt-4.1`. Such a model's price is set by giving the whole map as JSON
or from a file (`runtimes.openai.prices=@prices.yaml`). That replaces the map, so it needs the other prices too.
Alternatives considered:

- *A list of `{model, input, ...}`*: every edit replaces the whole list, merges across branches as one line, and
  duplicates are possible. Worse for everyone, to help only dotted names.
- *Escaping or quoting in config paths* (`prices."gpt-4.1"`): the right fix, but it changes how every config path
  parses (CLI, the core's path type, error details), so it's a change of its own, not this one.

Decided (owner, 2026-11-07): accept the limit here and document it in `docs/stagecraft/runtimes.md`. Escaping or
quoting keys in config paths (`gpt-4\.1` or `"gpt-4.1"`, syntax still to choose) is
[#303](https://github.com/troupe-run/troupe/issues/303), which stays open for later. It isn't part of this change.

### D6. The run's price: exact match on the resolved model, from config only

After the model is resolved, the price is `prices[model]` exactly, with source `theatre`. A near match (a dated
version, a different case) gets no price: matching more loosely would guess. There's no
`TROUPE_RUNTIME_<NAME>_PRICE...` variable. A price is a table, not a single value, and nothing yet asks to override it
per session. `troupe.core.runtimes` gains a `price` on the resolved runtime, set once the run's model is known. For
`config get --resolved`, that's the runtime's own resolved model, when it has one.

### D7. An estimate prices every token or is absent

The rule (spec: runner-protocol, "An estimate covers every token the run used, or is absent"): `inputTokens` and
`outputTokens` must be reported. A rate for a counter that wasn't reported means the run's tokens are unknown. A counter
with tokens and no rate means part of the run is unpriced. Either way, no estimate. Pricing cache reads at the input
rate, or treating an unreported counter as zero, would produce a number that looks exact and isn't. A counter at 0
with no rate costs nothing, so it doesn't block the estimate.

Arithmetic: `Σ tokens × rate / 1_000_000`, as floats, rounded to 10 decimal places, as `_Spend.cost()` already rounds.
Exact to well under a cent for any realistic run.

### D8. The runner works the estimate out, with the SDK's estimator

The host could work it out instead, from the result's usage and the price it resolved. That would be one place, and
it wouldn't need D9's check. But the runner is the one that knows whether its service reported a cost: some responses
may carry one and others not, as the OpenAI runner already handles. It also knows how its engine's counters map onto
the contract's. The issue frames it as the runner's report. So the runner works it out, and the duplication is removed
by one function in the SDK, `troupe_plugin_sdk.cost.estimate(usage, price) -> float | None`, standard library only.
The OpenAI runner calls it when `_Spend.cost()` is `None` and the run has a price.

### D9. The host refuses an estimate it gave no price for

`troupe.core.runners.host` already checks a run's events beyond the schema (the first event is `init`, nothing comes
after `result`). It gains one check: `estimatedCostUsd` with no `price` in the `run/start` it sent is a protocol
violation, with a problem that says so. It's cheap, and it turns "a runner guessed" into an outcome rather than a
number in the store. The host doesn't recompute the estimate to check its value. That would re-derive D7 in core, and
a runner that gets the arithmetic wrong is a bug in that runner, caught by its own tests.

### D10. Recording the price

`$defs/resolved` gains optional `price: {value, source}`, so `Run.Started`, the rehearsal and `config get --resolved`
all show it, through the generated pydantic model `ResolvedRuntime`, and the client messages that carry it. A run's
estimate can then be checked from its `Run.Started` price and its `result` usage alone. `RunRuntime.run_start()`
passes the bare price to `run/start`.

### D11. Compatibility and release

Every addition is optional. An older troupe never sends a price, so a newer runner never sends it an estimate. The
other direction isn't free. A runner built on an older SDK parses `run/start` strictly, so it refuses a
`runtime.price` it doesn't know, but only when the theatre has priced the run's model. The runners in this repository
move with the SDK in this change, as with every contract change so far. A runner outside the repository needs the new
SDK before anyone prices its models. That's acceptable while the contract is a draft, and the changelog says so. The
contract stays version 0, the draft. Commits that touch `protocol/` are `feat(protocol)`, and release-please writes
the changelog. No spec Purpose changes, so there's no infrastructure pull request.

### D12. Testing

- **SDK estimator:** example tests from the specs' scenarios, plus a hypothesis property test. It generates usages and
  prices with each counter and rate present or absent, and checks that the estimator returns `None` exactly when an
  independent statement of D7's rule says so, and otherwise the sum. The scenario's 6.35 is checked exactly.
- **Schemas and types:** the existing SDK-vs-schema drift tests cover `estimatedCostUsd`, `price` and
  `RunStartRuntime.price`. Schema tests cover both costs together, a price without `output`, a negative rate, and an
  unknown price field.
- **Config and resolution:** `config set` of a price, a bad price refused with its path, a dotted model's name set via
  the whole map as JSON, the exact-match and environment-model scenarios, and `config get --resolved`.
- **End to end through perform** with the scripted runner: its runtime check gains `price`, which proves that
  `run/start` carried the price `Run.Started` recorded. A scripted result with `estimatedCostUsd` and no price
  produces the protocol-violation outcome. With a price, the result is recorded as sent.
- **OpenAI runner:** the fake endpoint's usage with and without a price, cache reads without a `cacheRead` rate, no
  usage, and a service that reports a cost (no estimate). The fixture replays get no estimate, since their runs have
  no price.
- **Unchanged behaviour:** the existing tests for `costUsd`, and runs with no price, pass without edits. The OpenAI
  runner's "reports no cost" fixtures stay byte-identical.

## Risks / Trade-offs

- [A person's price goes stale, so estimates drift from the bill] → it's marked as an estimate, and `Run.Started`
  records the price used, so drift can be seen and recomputed. Prices aren't shipped, so troupe never adds staleness
  of its own.
- [Dotted model names can't be priced one at a time] → the whole map as JSON or a file works today. Documented, and
  #303 tracks escaping or quoting in config paths (D5).
- [The estimate relies on the input-token convention #293 will formalise] → the convention is what every runner here
  already does. If #293 changes it, D7's rule moves with it in that change.
- [A price with only `input` and `output` gives most OpenAI runs no estimate, because nearly every run reads from or
  writes to the prompt cache (the owner's live run: about 2,200 tokens read, 1,150 written)] → the runtimes docs and the
  OpenAI runner's README say to set `cacheRead` and `cacheWrite` too, with 0 for a kind the service doesn't charge for.
  (Raised by a side agent while building.)
- [The strict rule leaves the cost out more often than a lenient one would] → chosen on purpose. An absent cost is
  visible, and a wrong one isn't. Each refusal is a config fix (add the missing rate).

## Migration Plan

None. No stored data changes shape, and runs recorded before this have no price and no estimate, which stays valid.
Rollback is reverting the change.
