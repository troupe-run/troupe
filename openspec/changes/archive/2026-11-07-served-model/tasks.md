# Tasks

## 1. The contract and the SDK

- [x] 1.1 Add `served_model` to `protocol/schemas/runner/run-event.schema.json`: its definition (`runId`, `seq`,
  `type`, `model` with the runtime model's pattern and `maxLength` 256, described), both `oneOf` lists and
  `oversized.originalType`; copy it to troupe's carried `packages/troupe/src/troupe/protocol/runner/`. Verify
  `test_protocol_strict.py` and the carried-copy test pass, and that a 257-character or empty `model` and an extra
  field fail validation (new schema tests).
- [x] 1.2 Add `ServedModelEvent` to `troupe_plugin_sdk.runner` (with `MODEL_PATTERN`), to `EventType` and
  `EVENT_TYPES`. Verify `packages/troupe-plugin-sdk/tests/test_runner_types.py`'s mirror checks cover it and pass.
- [x] 1.3 Add `ServedModels` to the SDK (design D4): `note(model)` returns nothing for an empty, asked-for or
  already-noted name, a `served_model` body for a new one, and a `log` warning body for one outside the shape. Verify
  unit tests for each branch, and a hypothesis test that no name is emitted twice or for `init`'s model and every
  emitted name matches `MODEL_PATTERN`.
- [x] 1.4 Update `contributing/runners.md`'s run events table and rules (the new row: once per other model, before
  the event reporting the answer, never `init`'s, its shape, the `log` fallback). Verify the readme/doc tests that
  check it pass.

## 2. The host

- [x] 2.0 Add a `served_model` event step to the scripted runner's options schema. Verify
  `test_the_event_steps_cover_every_event_type_a_runner_sends` passes.
- [x] 2.1 In `core/runners/host.py`, keep `init`'s `engine.model` and the models reported, and treat a
  `served_model` naming either as a protocol violation naming the model. Verify host tests, through the scripted
  runner, for `init`'s model, a repeat, and an accepted `served_model` recorded as a `Run.Reported` event.
- [x] 2.2 Verify an oversized `served_model` is kept out of line with `originalType` `served_model` (a host test
  beside the existing oversized ones).
- [x] 2.3 Render `served_model` in `cli/render.py`'s `render_event` as its model, and regenerate the event reference
  (`scripts/docs_reference.py`). Verify a render test, and that the reference check passes with
  `docs/prompt-book/events.md` regenerated.

- [x] 2.4 Add `ServedModelEvent` to the client protocol's `HostEvent` (`core/client/messages.py`), which keeps its
  own list of event types (found applying: `troupe logs` and `perform` crashed on the new event). Verify a test that
  `HostEvent` holds every runner event type and the oversized one, and the logged-event round trip with a
  `served_model`.
- [x] 2.5 Make the plugin's fake Ollama echo the model a request asks for, as Ollama does, unless an answer names
  another, so stand-in runs report no `served_model` they wouldn't against Ollama. Verify the capture test and the
  Ollama suites pass.
## 3. The OpenAI runner

- [x] 3.1 In `loop.py`, replace `_noted_model` and its `info` log with `ServedModels`, built from the runtime's model
  and noted in `_count` for each reply. Verify `test_a_model_other_than_the_one_asked_for_is_noted_once` is replaced
  by fake-endpoint tests for: another model sent once before the reply's `turn` with no model `log`; the runtime's
  model sending nothing; a name with a control character sending a `log` warning and no `served_model`.
- [x] 3.2 Update the README's mapping row (a model other than the one asked for → `served_model`, once per model) and
  `contributing/runners.md`'s Responses API table. Verify `test_openai_readme.py` passes, and the recorded fixtures'
  expected events are unchanged (`test_openai_fixtures.py`).

## 4. The Claude Code runner

- [x] 4.1 In `mapping.py`, build `ServedModels` from `system/init`'s `model`, note each assistant record's
  `message.model` (skipping `<synthetic>`) before its `turn` and tool calls, and each `modelUsage` key in order
  before the permission-denial logs and the `result`. Verify mapping tests from built records on the recorded shapes:
  a fallback model, `<synthetic>`, a subagent's message, a `modelUsage`-only model, and one already reported.
- [x] 4.2 Verify the recorded fixtures' expected events are unchanged (`test_claude_code_fixtures.py`) and the
  mapping property tests still pass; update the README's and `contributing/runners.md`'s Claude Code mapping rows,
  verified by `test_claude_code_readme.py`.

## 5. The Ollama runner

- [x] 5.1 In `conversation.py`, read each answer's `model` into `_Answer` and note it with `ServedModels`, built from
  the model asked for, before the answer's `turn` or the `result`. Verify a fake-Ollama test where an answer names
  another model, and that the recorded fixtures' expected events are unchanged.
- [x] 5.2 Update the README's and `contributing/runners.md`'s Ollama mapping rows. Verify the plugin's readme test
  passes.

## 6. Integration

- [x] 6.1 Run `uv run scripts/check.py` and show it passing; then mark the pull request ready and cite the CI run on
  Linux, macOS and Windows for the last code change. After the rebase onto main (with #293 and #300), `scripts/check.py`
  passed locally on `1d39ca7`, whose last code change is `368395c` (all gates, tests in 248s), and CI on `1d39ca7`
  passed every leg on Linux, macOS and Windows: https://github.com/troupe-run/troupe/actions/runs/42438779883. (Before
  the rebase, a windows-latest Python 3.15 failure was the unrelated flaky test filed as #335.)
- [x] 6.2 Run `openspec validate served-model --strict` and show it passing.

## Workflow follow-up

- Commit as `feat(runner-protocol): ...` so the protocol release notes the new event.
- Act on Claude's review of the last push, archive on the branch, and hand the pull request to the owner to merge.
- After the merge: comment on #295 with the PR and the archived change, check it's closed and its card is Done, and
  tell #291 (the LM Studio runner) to send `served_model`.
