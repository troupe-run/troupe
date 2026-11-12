# Tasks

Every commit is signed and signed off (`git commit -S -s`), and `uv run scripts/check.py` passes before it (design D8).
## 1. The runner contract: `notRetried` (design D1, D2)

- [x] 1.1 Before changing anything, add tests to `test_runner_schemas.py` that pass on `main` today and must keep
  passing: an `error` result with each reason and no `notRetried` validates as `event`, `hostEvent` and in
  `run-ended`'s `outcome.result`; a `retry` with each of its five reasons validates. Verify: they pass on the
  unchanged schema.
- [x] 1.2 In `protocol/schemas/runner/run-event.schema.json`, name `$defs/retry`'s reason list `$defs/retryReason`,
  add `$defs/notRetried` (`side-effect`, with its description) and `$defs/result.notRetried`, with the rule that it's
  present only on an `error` result whose reason is a `retryReason`; copy the schema to
  `packages/troupe/src/troupe/protocol/`. Verify: each runner-protocol delta scenario is a test in
  `test_runner_schemas.py` (an `ok` result, reason `budget`, a value off the list, and the recorded `Run.Ended`
  case), they fail before the change and pass after, and 1.1's tests still pass.
- [x] 1.3 Document it in `contributing/runners.md` (the `result` row, a short "When a retry isn't safe" section after
  the reasons, and why Ollama, OpenAI and Claude Code never send it, design D6) and regenerate the event reference.
  Verify: `test_runners_doc.py` passes, and the docs check in `scripts/check.py` passes.

## 2. The SDK (design D4)

- [x] 2.1 Add `RetryReason` and `NotRetried` to `troupe_plugin_sdk.runner`, use `RetryReason` for
  `RetryEvent.reason`, add `ResultEvent.not_retried`, and refuse it in `__post_init__` on an `ok` result and beside a
  reason outside `RetryReason`, naming `notRetried`. Extend `test_runner_types_drift.py` to compare both literals with
  the schema. Verify: each plugin-sdk delta scenario is a test, mypy `--strict` passes, and the drift test fails when
  a value is added to the schema alone (checked once by hand, then reverted).

## 3. The outcome and the CLI (design D3)

- [x] 3.1 Add `notRetried` to `run.error-result`'s details in `protocol/schemas/error.schema.json` (and the packaged
  copy); in `troupe.core.runners.outcome`, pass it through and prepend its fix from one table keyed by value, with a
  test that every `NotRetried` value has an entry. Verify: each actor-runners delta scenario is a test in
  `test_run_outcome.py`, and every derived error validates against the error schema.
- [x] 3.2 Show it on the result's line in `troupe.cli.render`: `error (network, not retried: side-effect)`. Verify: a
  test in `test_cli_render.py`, and the existing result-line tests still pass.

## 4. The scripted runner

- [x] 4.1 Let a script's `result` step name `notRetried`, with the contract's rule in its options schema
  (`plugins/runner-scripted/.../options.schema.json`), and pass it through. Verify: each scripted-runner delta
  scenario is a test; a script with `notRetried` beside `quota` is refused with `scripted.invalid-script` naming
  `notRetried`.

## 5. A summary that hasn't ended (#313, design D7)

- [x] 5.1 Fix `test_client_messages.py`'s generator to draw `transcript`, `transcriptFormat`, `stderr`, `error` and
  `recording` only for an ended summary, and check `test_client_schemas.py`'s fixtures for a summary that hasn't ended
  carrying any of them. Verify: the property tests pass on `main`'s schema with the fixed generator.
- [x] 5.2 Forbid `transcript`, `transcriptFormat` and `stderr` in `protocol/schemas/client/run.schema.json`'s
  not-ended branch (and the packaged copy) and in `RunSummary._check`, naming the field, and say so in each field's
  description. Verify: the client-protocol delta's transcript and stderr scenarios are tests, failing before and
  passing after; a property test adds one of them to a drawn summary that hasn't ended and checks that the schema and
  `RunSummary` both refuse it.
- [x] 5.3 The same for `error` and `recording` (owner, 2026-11-11). Verify: the delta's error and recording scenario is a
  test, and 5.2's property test draws these two as well.
- [x] 5.4 Update the client protocol's docs where they describe a summary's fields (`contributing/` and
  `protocol/README.md`, whichever describe it). Verify: the docs check passes, and a search for "hasn't ended" in the
  docs finds no description that the schema doesn't enforce.

## 6. The LM Studio runner: moved to #379 (design D5)

Not built here. The owner decided (2026-11-12, through the orchestrating session) that #390 merges before #379 and
doesn't wait for it, and that #379's session adopts the field in the LM Studio runner when it rebases onto this change.
What it adopts, as agreed with that session:

- An `lm-studio-runner` delta: a connection lost or unreachable after a tool call has been carried out or answered
  ends `network` with `notRetried` `side-effect`; a message timeout, the turn limit and the budget carry none.
- `_from_error` sets `notRetried` for `lost` and `unreachable` after a call, and the "a retry could run a tool twice"
  sentence follows the same condition.
- `test_a_lost_connection_after_a_call_isnt_retried` asserts the field; tests pin that a timeout after a call has
  neither the field nor the sentence, and that the turn limit and budget carry none; the runner's README and
  `contributing/runners.md`'s LM Studio section say so.

## 7. Integration

- [ ] 7.1 Run `uv run scripts/check.py`, writing its output to a scratch file. Verify: it passes locally, and CI passes
  on Linux, macOS and Windows once the PR is marked ready, cited on the last code change.
- [ ] 7.2 `openspec validate run-protocol-retry-and-summary --strict`. Verify: it reports the change valid.

## Workflow follow-up

- No spec is added or removed and no Purpose changes, so infrastructure's `oob/troupe-spec-purposes.json` needs no
  pull request; re-check at archive.
- Open a draft PR that says `Closes #313` and refers to #378, which stays open until #379 adopts the field; act on
  Claude's review; mark it ready; archive on the branch; hand it to the owner to merge.
- Set #378's and #313's cards to In Progress when this branch's work starts. After the merge, comment on both with the
  PR and the archived change; check #313 is closed and its card says Done; #378 stays open, In Progress, for #379.
- Tell the track-b-11-291 session when this change merges, so #379 can rebase and adopt the field (group 6).
