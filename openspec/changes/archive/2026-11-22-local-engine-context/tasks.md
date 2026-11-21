# Tasks

## 1. Fail first

- [x] 1.1 Add the derived fixture `lm-studio-conversation-cut-cached` (design D6): replies 0, 1 and 4 of
  `lm-studio-conversation-cut`, its provenance saying it's derived from them and why, `engine` `lm-studio`, and its
  expected events ending `context-length` after two requests' tool calls, with nothing from the third reply. Verify:
  the same replies replayed through the real runner on main's code act on reply 4 and send a fourth request, seen
  before any code change.
  Done: on main's code the replies 0, 1 and 4 replayed through the real runner sent a fourth request (scratch repro,
  2026-11-21); with the change the fixture replays to its expected events.
- [x] 1.2 Add loop tests for the usage scenarios ("LM Studio's cache reads counted once", "The same replies with the
  engine unknown"), the guard scenarios (cut with cache reads, on LM Studio and with no engine; Claude's cache reads
  rising), the window scenario (LM Studio's cache reads don't fill it) and the warning. Verify: the LM Studio and
  no-engine guard tests fail on main (the no-engine one with main's code as it is), and the Claude one and the
  API-defined usage one pass on main, which is what must stay the same.
  Done: on main (the harness without an engine), the no-engine cut and the warning failed, and Claude's rising cache
  reads, the API-defined usage and no warning without cache reads passed.

## 2. The engine on the runtime (design D1)

- [x] 2.1 Protocol: `$defs/engine` and `resolved.engine` in `runtime.schema.json`, `engine` in
  `config/runtime.schema.json`, `runtime.engine` in `runner/run-start.schema.json`, and the copies under
  `packages/troupe/src/troupe/protocol/`. Verify: the protocol's strictness and copy tests pass.
- [x] 2.2 Core: `engine` in `troupe.core.runtimes` (the field, its pattern and accepted words from the one enum, the
  environment override, `Resolved`, `to_data`, `RunRuntime.to_data` and `run_start`), and the built-ins' engines in
  `troupe.core.defaults`. Verify: runtimes tests for config (accepted, refused naming the values), the environment
  (override, empty, malformed as `runtime.invalid-value` without the value), `config get --resolved`, the run's start
  and `run/start` (present, absent, never null), and the built-ins.
- [x] 2.3 Rehearsal and the CLI's resolved-runtime view show the engine. Verify: a rehearsal test on `anthropic`
  shows `claude` from `default`, and the config get output test shows the engine.
  Done: the rehearsal test uses a theatre-set engine (spec: runs, scenario reworded to match), and `config get
  --resolved runtimes.anthropic` shows `engine: claude (from default)`.
- [x] 2.4 SDK: `RunStartRuntime.engine` (`RuntimeEngine | None`, with `RUNTIME_ENGINES`), checked against the set.
  Verify: SDK tests parse present and absent, refuse `vllm` naming `runtime.engine`, and compare the SDK's set with
  the schema's enum.

## 3. Counting and guarding per engine (design D2 to D5)

- [x] 3.1 Add `Engine` and `ENGINES` to `context.py`, each entry pinned, and read the engine in `runtime.py`.
  Verify: table tests check one entry per schema value, their accounting and pins, and that every `Signal.engine`
  names an entry.
- [x] 3.2 Add `prompt_readings` and change `shrank` to compare readings (D3). Use them in the guards and the estimate.
  Verify: the context unit and property tests pass (a growing conversation never shrinks under any accounting; a drop
  in any reading is caught when it isn't known), and so do 1.2's guard and window tests.
- [x] 3.3 Count usage per engine in `_Spend.add` (D4). Verify: 1.2's usage tests and the budget test on corrected counts
  pass.
- [x] 3.4 Send the one-time warning (D5). Verify: 1.2's warning tests pass.
- [x] 3.5 Name the engine in every fixture's provenance, hand it to the replay's `run/start`, and update the LM Studio
  fixtures' expected usage (D6). Verify: a test checks each fixture names an engine from the table, and every fixture
  replays, 1.1's included.
  Done: the capture tool takes `--engine` and writes it into the provenance, so a new capture names its engine too.

## 4. Docs

- [x] 4.1 `docs/stagecraft/runtimes.md`: the `engine` field, its values, its variable and the built-ins' engines.
  `contributing/runners.md`: `run/start`'s `runtime.engine`. Regenerate `docs/prompt-book/config-schema.md` if it's
  generated. Verify: the docs tests pass, and `grep -rn "CREDENTIAL_ENV" docs contributing` shows each list of
  runtime variables also names `_ENGINE`.
- [x] 4.2 The runner's README: usage per engine, replacing the #419 note; The context, saying the prompt is measured
  per engine and conservatively when the accounting isn't known; which engines can still lose content silently; and
  the LM Studio and Ollama runtime examples setting `engine`. Verify: the README test passes, and the README names
  each engine in `ENGINES`.

## 5. Verify the whole change

- [x] 5.1 Run `uv run scripts/check.py` once the orchestrator gives the slot and the load is under 40, with its output
  kept in a scratch file. Verify: it passes, and its summary line goes in the pull request.
  Done: the commit guard's full check on 2846a422, "check: all gates passed" (7223 passed, tests passed in 271.4s),
  and on b27881a7, which touched only `plugins/runner-anthropic`, the guard's `runner_anthropic` scope, "check: all
  gates passed" (5281 passed). Both summary lines are in the pull request; CI runs the whole suite on every OS once
  it's marked ready (5.2).
- [x] 5.2 Open the pull request as a draft (`Closes #418`, `Closes #419`), act on the review of the last push, and mark
  it ready once it's clean. Verify: `gh pr checks` shows every job passing on the head, on Linux, macOS and Windows.
  Done: PR #489. The review of 0fcc2a84 was clean, with every conversation resolved and `claude review completed`
  passed. Marked ready; CI run 44956910760 passed every `check` leg on Linux, macOS and Windows, Python 3.12 to 3.15.
  The archive push changes only specs, the archived change and test comments.

## Workflow follow-up

- Archive on the branch after the review is acted on, before the owner merges.
- After the merge, check #418 and #419 are closed and their cards say Done, and comment on each with the PR and the
  archived change.
