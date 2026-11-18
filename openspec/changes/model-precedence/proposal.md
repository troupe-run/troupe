# Proposal

## Why

troupe's settings follow one precedence: a setting sent with the run, such as an actor's, beats the person's
environment, which beats config's and troupe's defaults. An actor's `onContextFull` beats `DISABLE_AUTO_COMPACT`, for
example. The run's model is the one exception. `TROUPE_RUNTIME_<NAME>_MODEL` beats the actor's own `model`, so one
variable in a person's shell quietly changes the model of every actor on that runtime, including actors that chose a
model on purpose. The 0.2.0 docs sweep (#425) found this, and the owner decided on 2026-11-18 to make the model follow
the usual order in 0.2.0 (troupe-run/troupe#451).

## What Changes

- **BREAKING** (pre-1.0, no compatibility form): a run's model is the actor's `model` when it sets one, else the
  runtime's `TROUPE_RUNTIME_<NAME>_MODEL`, else the runtime's `model` in config. Today the variable comes first.
- The variable still sets the model for every actor on the runtime that names none of its own. That includes
  `troupe init`'s mistralrs actor, which names no model, so its documented setup keeps working.
- Nothing new is recorded. A run's start already records its model with its source (`actor`, `env` or `theatre`), and
  `troupe perform --rehearse` shows it, so which level won can already be read from every run (#295 records the model
  that served it).
- The `model` description in the actor config schema says the actor's model beats the variable, and the generated
  config models and schema reference follow. The runtimes help text that lists what sets a model, a docstring in
  `defaults.py`, and the Ollama runner's README state the new order.
- The user docs pages that state the order (`docs/stagecraft/runtimes.md` and the others) change in the 0.2.0 docs
  pull request, #460, rebased on this one, as agreed with that change's author.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runtimes`: "The run's model comes from the environment, the actor, then the runtime" becomes "The run's model comes
  from the actor, the environment, then the runtime", with a scenario for each level winning over the one below it.
  "A run's price is the price of its model"'s scenario where the environment's model has no price now names an actor
  that sets no model, since otherwise the actor's model would win.

## Impact

- `packages/troupe/src/troupe/core/runtimes.py` (`run_model`), and the tests in
  `packages/troupe/tests/test_runtimes.py` that pin the old order.
- `protocol/schemas/config/actor.schema.json` and its packaged copy, `packages/troupe/src/troupe/core/config/models.py`
  and `docs/prompt-book/config-schema.md` (generated from the schema).
- `packages/troupe/src/troupe/core/defaults.py`, `packages/troupe/src/troupe/cli/runtimes.py` (only if its wording
  states an order), `plugins/runner-ollama/README.md`.
- A person who relied on the variable to override an actor's own model now has to unset the actor's `model`, or set
  it, to change that actor's model.
