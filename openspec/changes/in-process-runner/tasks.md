# Tasks

## 1. An in-process runtime (core and contract)

- [x] 1.1 Make `endpoint` optional in the resolved runtime (`protocol/schemas/runtime.schema.json`), the config schema (`protocol/schemas/config/runtime.schema.json`) and `run-start.schema.json`'s `$defs/runtime`, with their packaged copies, and in the SDK's `RunStartRuntime`. Verify: schema tests accept a `run/start` runtime with no `endpoint` and refuse one with `endpoint: null`, and the SDK drift test passes.
- [x] 1.2 Add the built-in `mistralrs` (in-process: no endpoint, no credential) to the built-in runtimes in `core/defaults.py`, with "in-process" a property of the built-in. Keep "a runtime of your own needs an endpoint". Refuse `runtimes.mistralrs.endpoint` in config, and `TROUPE_RUNTIME_MISTRALRS_ENDPOINT` as `runtime.invalid-value`. Verify: runtimes tests for the scenarios "The in-process built-in", "An endpoint in config" and "An endpoint from the environment".
- [x] 1.3 Send no `endpoint` in `run/start` for an in-process runtime. Verify: a runs test for the runner-protocol scenario "An in-process runtime" (no `endpoint` field, not null).
- [x] 1.4 Add `endpoint: required | none | any` to `RuntimeFit`: `required` for ollama, openai and lm-studio, `any` for scripted. Make config fit and perform's `runtime.unfit` name a missing or unwanted endpoint. Verify: `test_runtime_fit.py` cases for "An in-process actor on a served runtime" and "A served actor on the in-process runtime", and every existing fit test still passes.
- [x] 1.5 Make the Ollama, OpenAI and LM Studio runners refuse a `run/start` runtime with no endpoint, each with its own invalid-runtime code naming `runtime.endpoint`, before any request. Verify: one test per runner.
- [x] 1.6 Document the built-in and the "no endpoint" fit in `docs/stagecraft/runtimes.md`. Verify: the docs checks in `scripts/check.py` pass.

## 2. The plugin's package and wiring

- [x] 2.1 Create `plugins/runner-mistralrs` (Apache-2.0, `troupe_runner_mistralrs`), depending on `troupe-plugin-sdk` and `mistralrs==0.9.5`, and `uv lock`. Wire it into the root `pyproject.toml` (sources, dev group, ruff, mypy, pytest, import-linter), `scripts/check-paths.toml` (a `runner_mistralrs` scope), release-please config and manifest, and `troupe-run`'s optional dependencies (`mistralrs` and `all`). Verify: `uv run scripts/runner_licences.py` passes, and the workspace bundle and install-docs tests pass.
- [x] 2.2 Add `mistralrs` to `RUNNERS` (`in_extra`, `runtime: required`, a fit with no endpoint, no credential and the built-in `mistralrs`), with an audition and an init note saying how to point `TROUPE_RUNTIME_MISTRALRS_MODEL` at a GGUF file. Verify: core tests for the base install refusing it with `runner.not-installed` naming `troupe-run[mistralrs]`, and the audition rehearsing.
- [x] 2.3 Package the check model `check_model/stories260K.gguf` with `PROVENANCE.md`: the weights from karpathy/tinyllamas `stories260K` (MIT), the GGUF from ggml-org/models, the MIT licence text, the SHA-256 `270cba1b…256d` and the date (design D10). Verify: a test checks the file's SHA-256 against the provenance and that the licence is recorded, and the built wheel holds both files.

## 3. The entry point and the protocol channel

- [x] 3.1 Write the entry point and `runner.py`'s main-thread reader and output lock (design D1). Keep the protocol on a duplicate of fd 1, point fd 1 at standard error, and rebind `sys.stdout`, all before `engine.py` imports `mistralrs` (D3). Add an import-linter contract so only `engine.py` imports `mistralrs`. Verify: a test that importing the entry module doesn't import `mistralrs`.
- [x] 3.2 Define the `Engine` protocol (load, chat, count tokens) in `port.py` with the error table, and the real implementation over `mistralrs` in `engine.py`; the table that classifies its `ValueError`s (Metal library, prompt over the model's length, KV capacity, other). Verify: unit tests of the table against each recorded message from the probe.
- [ ] 3.3 Test the protocol channel with the real engine. Run the runner process with the check model on standard output as a pipe, through `initialize`, a `run/start` the runner refuses after loading, and `shutdown`. Verify: every standard-output line parses as a contract message, the engine's log lines are on standard error, and the test passes on all three OSes in CI.

## 4. Before the acknowledgement

- [x] 4.1 Add the options parser and `options.schema.json`/`errors.schema.json` (`maxTurns`, `contextLength`, `temperature`, `seed`, `think`; `mistralrs.unknown-option`, `mistralrs.invalid-options`). Verify: the options scenarios, and a hypothesis test that the parser and the published schema agree.
- [x] 4.2 Check the runtime and the model file: `mistralrs.no-runtime`, `mistralrs.invalid-runtime` (endpoint or credential, holding no part of `TROUPE_RUNTIME_CREDENTIAL`), and an absolute path to an existing file with the GGUF signature (`mistralrs.invalid-model`, `mistralrs.model-not-found`, naming `TROUPE_RUNTIME_MISTRALRS_MODEL`). Verify: tests for each spec scenario, none of which loads a model.
- [x] 4.3 Publish `requirements.json` (`mistralrs` `0.9.5`, with why), and refuse another installed version with `runner.requirement-unmet`. Verify: the spec scenario, with the installed version stubbed.
- [ ] 4.4 On macOS, load the check model before answering `run/start`, and refuse a Metal library failure with `mistralrs.unsupported-python`, naming `sys.executable` and the version, with the `uv tool install --managed-python` fix (D4). Verify: a stand-in test for the refusal, a test that Linux and Windows load nothing before answering, and on CI's macOS legs (uv-managed Pythons) the check passes with the real engine.

## 5. Loading the model after the acknowledgement

- [x] 5.1 Load on the worker after the acknowledgement, with a `log` event, within `LOAD_TIMEOUT_SECONDS`. A failure or overrun ends the run with `configuration` and the engine's message. On Metal, pass the window as the KV budget. Verify: stand-in tests for a refused load, an overrun, and "End of input during the load".
- [x] 5.2 Set the window: `contextLength`, else `DEFAULT_CONTEXT_LENGTH` lowered to the model's length. A `contextLength` above the model's length ends the run with `configuration`. Verify: tests for the three "always sets the context window" scenarios, the Metal one checking the load's KV budget through the stand-in.

## 6. The conversation

- [x] 6.1 Build each request: the character and direction first, the SDK's tools as function schemas, `temperature`/`seed`/`think`, no truncation, and no engine tools, callbacks, search or code execution. Verify: tests for "The character and the direction start the conversation" and "Every request offers the SDK's tools and nothing of the engine's own".
- [x] 6.2 Carry out tool calls with the SDK in order, give a missing call id one of the runner's, cap each result to the window's share with the cut note, and map answers to `turn`, `tool_call` and `tool_result` events, with reasoning only in the transcript. Verify: the spec scenarios for tool calls, turns and one tool result fitting the window.
- [x] 6.3 End the loop: `ok` on an answer with no tool call, `turn-limit` at `maxTurns`, the result's `turns`, duration and `usage` with no cost or cache counter. Map every error through one reason table (`context-length`, `configuration`, `turn-limit`, `engine`, `runner`) with no retries. Verify: tests for each reason, and that no `retry` event is ever sent.
- [x] 6.4 Send transcript records: the first request and each added message as `sent`, each response as `received`, serialised from the library's objects, with or without kinds by capability. Cut event text to `eventMaxBytes`. Verify: the transcript and summary scenarios, and that re-sent history isn't sent again.

## 7. The context window

- [x] 7.1 Count the conversation before each request (D7), ask for at most the room left less `TOKEN_MARGIN`, and end a run told `fail` with `context-length` when there's no room. Map a `length` stop and the engine's two length refusals to `context-length` without carrying out that answer's tool calls. Verify: tests for "Each answer is bounded by the room left in the window" and "A run never carries on past its context window", and a hypothesis test that `max_tokens` never exceeds the room left.
- [x] 7.2 Compact in a run told `compact`, before a request over the SDK's `COMPACT_AT_SHARE` and after a refusal or `length` stop, using the SDK's `compaction`, with the `context` event. End with `context-length` when nothing is left to remove. Verify: tests for both compaction requirements' scenarios.

## 8. Cancel, end of input and shutdown

- [x] 8.1 On `run/cancel`, end of input or `shutdown`, set the stop flag under the output lock, acknowledge, flush, and `os._exit` within `STOP_GRACE_SECONDS`, abandoning the engine call (D2). Verify: stand-in tests that no event follows the acknowledgement and no further tool call is carried out.
- [ ] 8.2 Test cancel, end of input and shutdown as processes: with the stand-in holding a request open (as the engine does, the GIL released) and holding the load; and with the real engine and the check model, while it loads and answers. The check model can't chat and answers in milliseconds, so a real model mid-generation is the live test's (9.3). Verify: the runner process exits within its grace on all three OSes in CI.

## 9. Fixtures, conformance and the live test

- [x] 9.1 Write the engine stand-in and the test-only entry script that hands it to `runner.main`, and add a conformance test for the runner in `packages/troupe/tests/test_runner_conformance.py`. Verify: every conformance check passes.
- [x] 9.2 Write `tools/capture_mistralrs.py`, and capture the fixtures (`tool-call`, `two-calls`, `effects-refused`, `length-stop`; design D10 says why there's no compaction one) with Qwen3-0.6B Q8_0 locally, at one heavy run at a time with load under 40. Add the fixture replay test. Verify: each fixture replays to exactly its events and transcript records.
- [x] 9.3 Add the live test, run only when `TROUPE_LIVE_MISTRALRS` names a model file: a run with a tool call to its result, and a cancel while the model generates a long answer, exiting within the grace. Verify: it's skipped naming the variable without it, and passes locally with Qwen3-0.6B.

## 10. Docs

- [x] 10.1 Write the plugin README, with every setting in `defaults.py` documented and a test that each has a row. Verify: the README test passes.
- [x] 10.2 Update `docs/opening-night/install.md` (the extra, and on macOS `--managed-python` with why), `contributing/runners.md`, `plugins/README.md` and the changelog. Verify: the docs checks and `test_user_docs_pages.py` pass.

## 11. Warming the engine before the first run (owner, 2026-11-14)

- [x] 11.1 Measure on fresh macOS CI runners whether a check-model load cut off mid-compile leaves a usable cache (design D4). Verify: the table in D4, from runs killed at 3, 8 and 12 s.
- [x] 11.2 Add the runner's `--warm-up` mode, writing one JSON line, with the same refusal as the run-time check. Verify: tests for the three scenarios of "The runner warms its engine when troupe asks, outside any run".
- [x] 11.3 Add `warm_up` to runner entries, `RUNNER_WARM_UP_TIMEOUT_SECONDS`, `troupe.core.runners.warm_up` and its three notices, and run it from `troupe init --audition` (not a rehearsal). Verify: tests for each notice and for "Init with an audition warms its runner's engine", and the notice catalogue tests.
- [x] 11.4 Document the warm-up: the runner guide (`warm_up` and the notices), the plugin README and the install page. Verify: the docs checks pass.

## 12. The whole check

- [x] 12.1 Run `uv run scripts/check.py` in full, with the log kept in a scratch file. Verify: every gate passes.

## Workflow follow-up

- Raise the infrastructure issue (board, 0.2.0) and its OpenSpec change in a helper worktree
  `../track-b-12b-414-infrastructure-...`. It adds `mistralrs-runner`'s Purpose to `oob/troupe-spec-purposes.json`,
  merged right after this pull request. Tell the orchestrator its issue and path.
- Draft PR closing #414, Claude's review, ready, archive on the branch, owner merge, after-merge comment.
