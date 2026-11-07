# Proposal: a cost estimated from a price, marked as one

Issue: [troupe#292](https://github.com/troupe-run/troupe/issues/292). Found building the OpenAI runner
([troupe#162](https://github.com/troupe-run/troupe/issues/162), change `openai-style-runner`, design D9 and D12 gap 2).

## Why

The runner contract's `result.costUsd` is "what the run cost, as the engine reports it". OpenAI's Responses API
reports tokens and no price, so an OpenAI run has no cost at all, and only its token budget bounds spend. A price per
model would give an estimate, but contract version 0 has nowhere to put one that a reader can't mistake for a cost the
service reported. The contract is still a draft, so this is the cheap time to add it.

## What Changes

- **The `result` event gains `estimatedCostUsd`**: what the run would cost at the price troupe gave the runner, in US
  dollars. It's a field of its own, not `costUsd` with a source flag beside it, so a reader that only knows
  `costUsd` sees no cost rather than an estimate it takes for a reported one. A result carries `costUsd` or
  `estimatedCostUsd`, never both: a runner estimates only when the service reports no cost.
- **A price comes only from troupe, in `run/start`.** A runtime's config gains `prices`, keyed by model, each price in
  US dollars per million input, cache-read, cache-write and output tokens. troupe looks up the run's model there and,
  when it finds a price, passes it in `run/start`'s `runtime.price`. troupe has no built-in prices, and a runner has
  none of its own: a price troupe didn't give is a guess.
- **A missing price leaves the cost absent, never guessed.** No price for the run's model, a usage counter the
  service didn't report, or a counter with tokens but no price for it: each leaves `estimatedCostUsd` out.
- **troupe refuses an estimate it didn't ask for.** A `result` with `estimatedCostUsd` from a run whose `run/start`
  carried no price is a protocol violation.
- **The run's record says which price it used.** `Run.Started` already records the resolved runtime; it gains the
  price with its source, so an estimate can be checked against the tokens and the price that made it.
  `troupe config get --resolved` shows the runtime's prices.
- **The plugin SDK gains one estimator** that runners share: tokens and a price in, an estimate or nothing out.
- **The OpenAI runner estimates** when the service reports no cost and `run/start` carries a price. Its spec's "The
  runner SHALL NOT estimate a cost" is replaced.
- **The scripted runner can script `estimatedCostUsd`**, so troupe's tests can drive both the valid case and the
  violation.

Not **BREAKING**: every new field is optional. A runner sends `estimatedCostUsd` only when `run/start` carried a
price, which a troupe from before this change never sends. Released as a protocol change (a `feat(protocol)` commit;
release-please writes the changelog).

Out of scope: budgets in money (later, once a cost can be trusted, per the issue); showing cost in `troupe status` or
`logs` (nothing shows `costUsd` today either); a published price table; what `usage.inputTokens` counts
([#293](https://github.com/troupe-run/troupe/issues/293)), which this change relies on as the runners already apply
it (cache reads and writes excluded).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runner-protocol`: the `result` event's estimate, the price in `run/start`, and the host's refusal of an estimate
  it gave no price for.
- `runtimes`: a runtime's `prices` by model, the price chosen for a run's model, and its place in the resolved
  runtime (`config get --resolved`, `Run.Started`).
- `runs`: a run's start, and a rehearsal, show the run's price with its source.
- `openai-runner`: cost is reported as the service reports it, or estimated from troupe's price when it reports none.
- `plugin-sdk`: the shared estimator.
- `scripted-runner`: a scripted result can carry `estimatedCostUsd`.

## Impact

- `protocol/schemas/runner/run-event.schema.json` (result), `run-start.schema.json` (runtime), `protocol/schemas/
  runtime.schema.json` (a price, the resolved runtime), `protocol/schemas/config/runtime.schema.json` (`prices`), and
  their copies under `packages/troupe/src/troupe/protocol/`.
- Core: `troupe.core.runtimes` (resolving the run's price), the run start that builds `run/start` and `Run.Started`,
  `troupe.core.runners.host` (the violation check).
- `packages/troupe-plugin-sdk` (`ResultEvent`, the runtime hand-off type, the estimator).
- `plugins/runner-openai` (loop's cost), `plugins/runner-scripted` (options schema).
- Docs: `contributing/runners.md`, `docs/stagecraft/runtimes.md`, `plugins/runner-openai/README.md`; the generated
  config and event reference.
- No spec Purpose changes, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json` is untouched.
