# Tasks

Full checks (`uv run scripts/check.py`) are sequenced by the orchestrator: ask before each one, and check `uptime`
first.

## 1. The model's order (design D1, D3)

- [x] 1.1 Tests first in `packages/troupe/tests/test_runtimes.py`, one per scenario of "The run's model comes from the
      actor, the environment, then the runtime": the actor's model beats the variable and the runtime's model; the
      variable beats the runtime's model when the actor sets none; the runtime's model when neither is set; no model
      anywhere is refused. Each checks the model's source as well as its value. Rename the requirement comment. Verify
      the actor-beats-environment test fails on main and the others pass on main. Done: 3 level tests; only the actor-beats-environment one failed on main
- [x] 1.2 A test in the runs tests that a performed run's start records the actor's model with source `actor` while
      `TROUPE_RUNTIME_<NAME>_MODEL` is set (runs spec, "A run's start records its runtime and where each value came
      from"). Verify it fails on main. Done: `test_perform_runtime.py`, failed on main
- [x] 1.3 Change `run_model` in `packages/troupe/src/troupe/core/runtimes.py` and its docstring. Verify 1.1 and 1.2
      pass, and every test in `test_runtimes.py` and the runs tests passes. Done: 158 passed (`test_runtimes.py`, `test_perform_runtime.py`)
- [x] 1.4 The price tests (`test_the_model_from_the_environment_has_no_price`, `..._is_priced_when_config_prices_it`)
      pass an actor with no model, as the price requirement's scenario now says. Verify they pass, and fail if the
      actor's model is put back. Done: with the actor's model back, the env model is gpt-b (priced) and the price isn't gpt-a's
- [x] 1.5 Check the mistralrs setup still reaches its model from `TROUPE_RUNTIME_MISTRALRS_MODEL` (its actor sets
      none). Verify the init and mistralrs tests that cover it pass. Done: `test_init.py`'s mistralrs actor sets no model; 150 passed (cli_config, cli_init, init, runtime_fit)

## 2. What states the order next to the code (design D4)

- [x] 2.1 The `model` description in `protocol/schemas/config/actor.schema.json`: the actor's model overrides the
      variable, which overrides the runtime's. Copy it to the packaged schema and regenerate the config models and
      `docs/prompt-book/config-schema.md` with the project's generators. Verify the generated-file and schema-copy
      checks pass. Done: package_schemas, generate_models and docs_reference `--check` pass
- [x] 2.2 The docstring of `defaults.BUILT_IN_RUNTIMES`, the help text in `packages/troupe/src/troupe/cli/runtimes.py`
      (only if it states an order) and `plugins/runner-ollama/README.md`'s sentence on the order. Verify
      `git grep` finds no other statement of the old order outside the pages #460 owns. Done: the Ollama README and
      `runtimes.py`'s module docstring changed. `defaults.py`'s docstring is about a runtime's own fields, still
      true, and `cli/runtimes.py` lists what sets a model with no order, so both stay. `git grep` finds the old order
      only in `docs/stagecraft/runtimes.md` (#460's) and the main spec (archive replaces it)
- [x] 2.3 Tell the 0.2.0 docs worker (#460) when this is pushed, with what changed, so its pages follow. Done:
      sent the new schema and README wording, and that `config get --resolved`'s output is unchanged

## 3. Integration

- [x] 3.1 Full check (`uv run scripts/check.py`), with the orchestrator's go-ahead, output kept in a scratch file.
      Verify it passes. Done: 7127 passed, 20 skipped, all gates passed (b5e3fd99, rebased on #458)

## Workflow follow-up

- Draft PR closing #451; act on Claude's review; mark ready; archive on the branch; owner merges.
- After the merge: issue closed, card Done, comment on #451 with the PR and the archived change.
