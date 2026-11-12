# Tasks

## 1. Contract and SDK

- [x] 1.1 Add the required `onContextFull` (`fail` | `compact`) to `run/start` in `protocol/schemas/runner/run-start.schema.json` and its packaged copy, and `on_context_full` to the SDK's `RunStartParams`. Verify: the SDK drift test passes, and new schema tests refuse a `run/start` without it and one with `summarise`.
- [x] 1.2 Add `troupe_plugin_sdk.compaction`: `Candidate`, `choose`, `stub` and `Estimate`. Move `BYTES_PER_TOKEN` into the SDK's `defaults.py` with `COMPACT_AT_SHARE` and `COMPACT_TO_SHARE` (design D6, D7). Verify: unit tests for the plugin-sdk scenarios, and a hypothesis property test that `choose` never picks a protected result and stops at the target.
- [x] 1.3 Update the scripted runner to accept `onContextFull` and ignore it. Verify: a test plays a script with `compact` unchanged, and the conformance suite passes.

## 2. Config, policy and perform

- [x] 2.1 Add `onContextFull` to the actor config schema, and its description. Verify: config tests for the config spec scenarios (`compact` recorded, `summarise` refused naming the path and both values).
- [x] 2.2 Add the `compaction` policy setting (`actors` | `all` | `none`, default `actors`) to `core/policy.py`, as an enum setting beside the flags. Verify: policy tests for the default, the env source and `policy.invalid-value` naming all three values.
- [x] 2.3 Resolve each run's `onContextFull` in `perform` (design D2 table), send it in `run/start`, and refuse with `policy.compaction-forbidden` under `none` before the run's start is recorded. Add the error code to the catalogue together with the code that raises it. Verify: runs tests for every cell of the D2 table and for the refusal, which records no run and starts no runner.
- [x] 2.4 Record `onContextFull` and its source in the run's start (the run-started event schema and the runs aggregate), as the run's runtime is recorded. Verify: runs tests for the `actor`, `policy` and `default` sources.

## 3. Ollama runner

- [x] 3.1 Compact before a request when it's `compact` and the estimate is over `COMPACT_AT_SHARE` of the window: stub chosen `tool` messages in `_messages` and send the `context` event before the request. Verify: unit tests for the ollama-runner scenarios (protected messages unchanged, one `truncated`/`runner` event with equal message counts, nothing changed when told `fail`).
- [x] 3.2 After a `CONTEXT_REFUSAL` in a run told `compact`, compact and send the request again without counting a turn. End with `context-length` and the "nothing more to remove" message when `choose` returns nothing. Verify: unit tests for both scenarios, and the existing `context-overflow` fixture still ends with `context-length` when told `fail`.
- [x] 3.3 Capture `context-compacted` and `context-compaction-exhausted` fixtures from real Ollama with `tools/capture_ollama.py` and a small `contextLength`, and play them in the fixture tests. Verify: the fixture tests pass, and the first ends `ok` with a `context` event.

## 4. OpenAI runner

- [ ] 4.1 On `context_length_exceeded` in a run told `compact`, stub the chosen `function_call_output`s down to `COMPACT_TO_SHARE` of the last accepted request's input tokens, send the `context` event and the request again, with the turn count and usage unchanged. End with `context-length` when nothing is chosen. Verify: unit tests for the openai-runner scenarios, including reasoning items and `function_call`s sent unchanged.
- [ ] 4.2 Add stand-in fixtures for a refusal followed by success, and a refusal with nothing left to remove, captured without a real credential. Verify: the fixture tests pass.

## 5. Claude Code runner

- [ ] 5.1 In `command.build()`, write `autoCompactEnabled` from `onContextFull`, and leave `DISABLE_AUTO_COMPACT` out of the environment when it's `compact`, sending a `warning` `log` after `init` naming it when it was set (design D8, D9). Verify: command and runner tests for the claude-code-runner scenarios of "Claude Code compacts only when the run says compact".
- [ ] 5.2 In `mapping.py`, map `system`/`compact_boundary` to a `context` event (`compacted`, `engine`, `tokensBefore` from `pre_tokens` when valid), and `status` `compacting` / `compact_result` records to named debug logs. Verify: mapping tests, including a boundary in a run told `fail` and a `pre_tokens` that isn't a whole number.
- [ ] 5.3 Add a `--compaction` mode to `tools/capture_claude.py`: a stand-in that answers the compaction request with a summary, capture through `build()` with `compact`, and refuse to write without a `compact_boundary`. Verify: capture-tool tests for the refusal, and its existing context-limit refusal tests still pass.
- [ ] 5.4 Capture `compaction-proactive` and `compaction-reactive` with real Claude Code against the stand-in, and play them in the fixture tests. If the boundary record differs from design D8 or D10, follow the captured record and update the design in the same commit. Verify: the fixture tests pass, each with one `context` event before the next turn's events, ending `ok`.

## 6. Docs and the whole check

- [ ] 6.1 Document `onContextFull` on the actor reference page, `TROUPE_POLICY_COMPACTION` beside the other policy settings, and each runner's compaction behaviour on its runner page under `docs/`. Say that compaction changes what the model sees, and that a project's settings `env` can still turn Claude Code's off. Verify: the docs checks in `scripts/check.py` pass, and the generated reference is current.
- [ ] 6.2 Run `uv run scripts/check.py` in full, keeping the log in a scratch file. Verify: every gate passes.

## Workflow follow-up

- Draft PR closing #310. Act on Claude's review, mark it ready, then `/opsx:archive` on the branch before the owner merges.
- After the merge: check #310 is closed and its card says Done, and comment with the PR and the archived change.
