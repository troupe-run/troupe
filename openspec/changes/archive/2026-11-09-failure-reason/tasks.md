# Tasks

The schema, the SDK, core and all four runners land in one pull request (design, Migration Plan), so main never has a
runner the contract refuses. Groups 2 to 6 can each leave the full suite red only for runners not yet moved; each
group's own tests pass when it's done.

## 1. Re-check the inventory before building on it

- [x] 1.1 Re-read every place each runner sends an `error` result (Claude Code `mapping.py` `_result`, Ollama
  `conversation.py` `_result`/`fail`, OpenAI `exchange.py` `classify` and `loop.py`, scripted `runner.py`), and check
  D6 names a reason for each. If a failure isn't covered, or the list in D2 needs to change, stop and update this
  change (`/opsx:update`). Verify: the failure-to-reason list is in the first apply commit's message, or the artifacts
  are updated and `openspec validate failure-reason --strict` passes.

## 2. The contract (design D1, D2, D3, D7)

- [x] 2.1 Add `reason` to `run-event.schema.json` `$defs/result` (the fifteen values, each described), required for
  `error` and forbidden on `ok` in `$defs/result` itself; regenerate troupe's packaged copy
  (`scripts/package_schemas.py`). Verify: `test_runner_schemas.py` gains tests that an `error` result without a
  reason, one with `timeout`, and an `ok` result with `budget` each fail to validate as a runner's event, as a
  `hostEvent` and in `run-ended`'s outcome; that no `$dynamicRef` reaches `reason`; and `test_protocol_strict.py`
  passes.
- [x] 2.2 Write each scenario of the runner-protocol delta that the schema alone can't check as a host test: an `error`
  result without a reason from a scripted `rawStdout` line crashes the run with `runner.protocol`; a recorded
  `result` event without a reason is refused naming `reason` when read back as a logged event. Verify: those tests pass, and fail with the
  SDK's check removed (the host parses a runner's events with the SDK).
- [x] 2.3 Document the result's `reason` in `contributing/runners.md` (the events table, a "Why a run failed" section
  with D2's table and D3's rule for `other`, the last-retry rule, and a cancelled result) and in `protocol/README.md`
  where it describes runner events. Verify: `uv run scripts/check.py`'s docs checks pass, and every reason in the
  schema appears in the section (a test compares them).

## 3. The SDK (design D5)

- [x] 3.1 Add `FailureReason` and `ResultEvent.reason` to `troupe_plugin_sdk.runner`, and refuse an `error` result
  without a reason and an `ok` result with one in `__post_init__`. Verify: `test_runner_types.py` covers each SDK
  scenario (building and parsing an `error` result without a reason are refused naming `reason`; `ok` with one is
  refused), and the drift test compares
  `FailureReason` with the schema's enum and fails when a value is added to only one.

## 4. The outcome and surfaces (design D4)

- [x] 4.1 Add `reason` to `run.error-result`'s details in `error.schema.json` (by `$ref` to the
  contract's enum, required), and the per-reason problem and fix table to `troupe.core.runners.outcome`, keyed by
  `FailureReason`. Verify: `test_run_outcome.py` has the authentication and budget scenarios, and a test
  over every `FailureReason` that each outcome validates against the error schema and has its own fix, which fails
  when a reason has no entry.
- [x] 4.2 Show the reason in the CLI's line for a `result` event (`render.py`). Verify: a CLI test for `troupe perform`
  with a scripted `turn-limit` result shows the turn-limit problem and fix and exits with the failure code, and
  `troupe logs` shows `error (turn-limit): …`.
- [x] 4.3 Update the outcomes table in `contributing/runners.md`, `docs/the-company/performances-and-runs.md` ("How a
  run ends"), `docs/prompt-book/events.md` and any generated reference that shows `run.error-result`'s details.
  Verify: the docs checks pass, and the generated references are regenerated with no diff left.

## 5. The scripted runner (spec: scripted-runner)

- [x] 5.1 Add `reason` to the scripted runner's `result` step in its options schema (by `$ref`, required for `error`);
  send `cancelled` for `honour-with-result`, and `other` for its own check failures; update every script and fixture
  in the repository that sends an `error` result (core's tests, the auditions) to name a reason. Verify: the
  scripted-runner scenarios pass as tests, a script with an `error` result and no reason is refused at `run/start`
  with `scripted.invalid-script`, and the scripted harness validates every message it sends; update its README.

## 6. The three engine runners (design D6)

- [x] 6.1 OpenAI: give every failure in `classify` and `loop.py` its reason from one table, including
  `model_not_found` and redirects as `configuration` and retries run out as the last retry's reason; update the
  recorded fixtures' expected events. Verify: each openai-runner delta scenario is a test, the fixtures pass, the
  conformance suite passes, and the README's "How a run ends" names the reasons.
- [x] 6.2 Ollama: give every failure its reason from one table; name the context window in the message only for a 400
  about the context size. Verify: each ollama-runner delta scenario is a test (including the other-400 one, which
  fails on today's code), the fixtures and conformance suite pass, and the README names the reasons.
- [x] 6.3 Claude Code: keep the last assistant `error` code and the last retry's reason as mapping state, and map a
  result's reason as the claude-code-runner delta orders it; update the fixtures' `expected.json` events. Verify: each
  delta scenario is a test, run against the recorded fixtures where the scenario names one and hand-made records
  shaped like them otherwise, the property tests and conformance suite pass, and `contributing/runners.md`'s Claude
  Code mapping section names the order.

## 7. Integration

- [x] 7.1 Run `uv run scripts/check.py`. Verify: it passes locally, and CI passes on Linux, macOS and Windows once the
  PR is marked ready, cited on the last code change.
  Done: passed locally (f4e1f097's own check, all gates), and CI run
  [42545201544](https://github.com/troupe-run/troupe/actions/runs/42545201544) passed all twelve jobs on 5ed6ceb8,
  whose tree holds the last code change.

## Workflow follow-up

- No spec is added or removed and no Purpose changes, so infrastructure's `oob/troupe-spec-purposes.json` needs no
  pull request; re-check that at archive.
- Act on Claude's review, archive on the branch, and hand the PR to the owner to merge.
- After the merge, comment on #296 with the PR and the archived change, close it if the PR didn't, and check its card
  says Done.
