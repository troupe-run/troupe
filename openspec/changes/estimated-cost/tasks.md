# Tasks

Each task's verification runs before it is ticked. `uv run scripts/check.py` passes before every commit.

## 1. Settle D5 before building on it

- [x] 1.1 Ask the owner to confirm design D5: prices keyed by model under `runtimes.<name>.prices`, with a dotted model's
  name priced by setting the whole map as JSON or from a file. Ask too whether to raise the follow-up issue for
  quoting in config paths now. Verified: the owner agreed (2026-11-07), and #303 was raised, open and on the roadmap
  board as Todo, for escaping or quoting keys in config paths, syntax to decide later. Design D5 records it.

## 2. The contract's schemas (design D1, D2, D4, D10)

- [ ] 2.1 Add `$defs/price` to `protocol/schemas/runtime.schema.json` (closed; `input` and `output` required;
  `cacheRead`, `cacheWrite` optional; each a number ≥ 0, described as US dollars per million tokens), and optional
  `price: {value, source}` to `$defs/resolved`. Verify: new cases in `packages/troupe/tests/test_runner_schemas.py`
  (or the runtime schema's tests) refuse a price without `output`, with a negative rate and with an unknown field, and
  accept a full one.
- [ ] 2.2 Add `estimatedCostUsd` to `run-event.schema.json`'s `result`, described as D1 says, with the
  `not: {required: [costUsd, estimatedCostUsd]}` rule. Reword `costUsd`'s description to "as the engine or its service
  reports it; never worked out by the runner". Add optional `price` (`$ref` to the definition in 2.1) to
  `run-start.schema.json`'s `runtime`. Copy all three schemas into `packages/troupe/src/troupe/protocol/`. Verify: a
  schema test refuses a result with both costs and accepts each alone, `diff -r protocol/schemas
  packages/troupe/src/troupe/protocol` shows no difference for the changed files, and the protocol copy check in
  `scripts/check.py` passes.
- [ ] 2.3 Add `prices` to `protocol/schemas/config/runtime.schema.json`: an object whose `propertyNames` use the model
  definition and whose values `$ref` the price. Regenerate the pydantic models and the generated config and event
  reference docs. Verify: the generators' drift checks in `scripts/check.py` pass, and the config reference lists
  `prices`.
- [ ] 2.4 Update `contributing/runners.md`'s `result` row and its `run/start` section: `estimatedCostUsd`, the rule
  that it's worked out only from `run/start`'s price, D7's rule, and `runtime.price`. Verify: the docs tests (links,
  generated sections) pass, and the text names each field as the schema does.

## 3. The SDK: types and the estimator (design D7, D8)

- [ ] 3.1 Add `Price` and `RunStartRuntime.price`, and `ResultEvent.estimated_cost_usd`, to
  `packages/troupe-plugin-sdk/src/troupe_plugin_sdk/runner.py`. Verify: `packages/troupe-plugin-sdk/tests/
  test_runner_types.py`'s drift tests pass, and fail when the new schema field is removed from the type (checked once,
  then restored).
- [ ] 3.2 Add `troupe_plugin_sdk.cost.estimate(usage, price) -> float | None` following D7, standard library only.
  Verify: tests for the plugin-sdk spec's scenarios (6.35 exactly; no usage gives `None`), and a hypothesis property
  test comparing it with an independent statement of the rule over generated usages and prices, with each counter
  and rate present or absent, pass.

## 4. Core: resolve, send and record the price (design D3, D5, D6, D10)

- [ ] 4.1 In `troupe.core.runtimes`, validate `prices` with the config schema and resolve the run's price once its
  model is known: an exact match, with source `theatre`, none otherwise, and no environment variable. Add it to the
  resolved form and to `run_start()`. Confirm `defaults.RUNTIMES` holds no price. Verify: tests for the runtimes spec's
  scenarios (built-in has no price, actor's model priced, environment model unpriced, near match unpriced) pass.
- [ ] 4.2 `config set` and `config get --resolved`: tests for pricing a model, refusing a price with an unknown field
  (naming the path), setting `runtimes.openai.prices` as JSON with the key `gpt-4.1`, and showing the resolved model's
  price with source `theatre`. Verify: those tests pass. Then run the documented `troupe config set` commands from
  4.4 in a scratch theatre and paste the output into the task's commit message.
- [ ] 4.3 `perform`: `run/start` carries the run's price and `Run.Started` records it with its source. The rehearsal
  shows it. Verify: a perform test with the scripted runner whose runtime check expects the price (needs 5.1), a check
  that `Run.Started`'s recorded price equals it, and a rehearsal test, all pass. The run-start scenario with no price
  still shows `credential` and nothing else.
- [ ] 4.4 Document prices in `docs/stagecraft/runtimes.md`: the units, an example for one model, the whole-map form for
  a model's name with a dot, exact matching, and that an estimate is marked as one and absent rather than guessed.
  Verify: the user-docs tests pass, and the documented commands run as written (as in 4.2).

## 5. The scripted runner (spec: scripted-runner)

- [ ] 5.1 Add `price` to the scripted runner's runtime check (expected price, or none), naming `price` when it differs,
  and `estimatedCostUsd` to its result step. Update `options.schema.json`. Verify: the scripted runner's tests for "The
  price differs" and "An estimate with no price" pass, and its schema tests pass.

## 6. The host's check (design D9)

- [ ] 6.1 In `troupe.core.runners.host`, treat a `result` with `estimatedCostUsd` as a protocol violation when the
  `run/start` it sent had no price. The violation's problem names the field and says troupe gave no price. Verify: a
  perform test with a scripted result carrying an estimate and no price ends with the protocol-violation outcome, and
  the same script on a priced runtime records the result as sent.

## 7. The OpenAI runner (design D8)

- [ ] 7.1 In `plugins/runner-openai/src/troupe_runner_openai/loop.py`, when `_Spend.cost()` is `None` and the run has a
  price, set `estimatedCostUsd` from the SDK's estimator. Verify: fake-endpoint tests for the openai-runner spec's
  scenarios (0.00078 with a price, nothing without one, cache reads without a `cacheRead` rate, no usage), plus a
  service that reports a cost giving `costUsd` and no estimate, all pass. The fixture replays pass unchanged.
- [ ] 7.2 Update `plugins/runner-openai/README.md`'s cost paragraph: reported when the service reports one, otherwise
  estimated from the runtime's price, and how to set one. Verify: `test_openai_readme.py` passes.

## 8. Integration

- [ ] 8.1 Run the full check (`uv run scripts/check.py`) and `openspec validate estimated-cost --strict`. Verify: both
  pass, and the existing `costUsd` tests (Claude Code mapping, OpenAI loop) pass without edits.
- [ ] 8.2 CI on Linux, macOS and Windows passes on the pull request's last code commit. Verify: cite the run.

## Workflow follow-up

- Open a draft pull request that closes #292 (`Closes #292`), with `feat(protocol)` among its commits, so the protocol
  releases.
- Act on Claude's review of the last push, mark the pull request ready, and archive on the branch before the owner
  merges.
- After the merge: comment on #292 with the pull request and the archived change, check it's closed and its card says
  Done.
