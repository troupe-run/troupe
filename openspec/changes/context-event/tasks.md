# Tasks

## 1. The contract's schema

- [x] 1.1 Add `$defs/context` to `protocol/schemas/runner/run-event.schema.json` (design D1 to D5): closed, required
  `runId`, `seq`, `type` (`const: "context"`), `kind` (`compacted`, `truncated`, `other`), `by` (`engine`,
  `runner`) and `message`, and optional `tokensBefore`, `tokensAfter`, `messagesBefore` and `messagesAfter`
  (`integer`, `minimum: 0`), each with a description that says what absent means. Add it to `$defs/event`,
  `$defs/hostEvent` and `$defs/oversized.originalType`. Verify with `uv run scripts/package_schemas.py` (which
  updates the packaged copy) and the protocol's strictness check passing on the schema.
- [x] 1.2 Schema tests in `packages/troupe/tests/test_runner_schemas.py`, one per spec scenario that the schema
  decides (spec: runner-protocol): a `compacted` and a `truncated` event validate; a `pruned` kind, a missing
  `message`, a missing `by`, `"tokensAfter": null` and a `turnsBefore` field don't; an event with only `tokensBefore`
  validates; an `oversized` event with `originalType` `context` validates under `hostEvent`, and a `Run.Reported`
  payload carrying a `context` event validates against `events/run-reported.schema.json`. Verify they fail on main's
  schema and pass after 1.1.

## 2. The SDK

- [x] 2.1 Add `ContextKind`, `ContextBy` and the frozen `ContextEvent(RunEvent)` to `troupe_plugin_sdk.runner`, and
  add it to `EVENT_TYPES` and `EventType` (design D7). Verify `test_runner_types_drift.py` passes with the new type,
  and fails when a field is dropped from either the schema's `context` or the dataclass (try it, then revert).
- [x] 2.2 Type tests in `packages/troupe-plugin-sdk/tests/test_runner_types.py`: `parse_event` reads a `context`
  event to a `ContextEvent`; what it writes validates against the schema; an unknown kind, an unknown `by` and an
  unknown field each raise a protocol error naming the event and the field. Verify they pass.
- [x] 2.3 Add `context_event(numbering, kind, by, message, *, tokens_before=None, tokens_after=None,
  messages_before=None, messages_after=None)` to `troupe_plugin_sdk.events` (design D7): check `kind` and `by` before
  taking a `seq`, leave out each `None` count, fit `message` with `fit`. Tests for each plugin-sdk scenario: only
  `tokensBefore` set and the next `seq` taken; a message over the summary limit cut on a character boundary with the
  event within `eventMaxBytes`; a kind off the list raises naming it and leaves `numbering.next_seq` unchanged.
  Add a hypothesis test that any message and any counts give an event that validates and fits `eventMaxBytes`. Verify
  the tests pass.
- [x] 2.4 Document the helper in the SDK's README (or its module docstring, whichever the SDK documents its other
  helpers in), and verify the documented call runs as written in a test or doctest.

## 3. Core: recording and showing it

- [x] 3.1 Add `p.ContextEvent` to `troupe.core.client.messages.HostEvent`, and verify `test_client_messages.py` and
  `test_client_schemas.py` pass with a logged `context` event round-tripping through `LoggedEvent` and validating
  against the client protocol's `logs-result` schema.
- [x] 3.2 Add a `context` summary to `troupe.cli.render.render_event` (design D6): the kind, `by`, and each count
  present, as `tokens <before> → <after>` and `messages <before> → <after>` with `?` for a side the event leaves out. Test the
  line for `compacted` by `engine` with only `tokensBefore` 41000, and for `truncated` by `runner` with both message
  counts. Verify the tests pass.
- [x] 3.3 End-to-end test through the scripted runner (spec: runs, "A context event is recorded and shown like every
  run event"): a script sending `init`, a `context` event and an `ok` result. Assert the run's events hold a
  `Run.Reported` with that event unchanged and with lineage, the outcome is `succeeded`, and `troupe logs` shows its
  line. Add the oversized case: a `context` event larger than `eventMaxBytes` is recorded as `oversized` with
  `originalType` `context` and its original in the artifact store. Add the host's protocol violations for a `context`
  event before `init` and after `result`. Verify they pass.

## 4. Docs

- [x] 4.1 Add `context` to the run events table in `contributing/runners.md`, with a short section on when to send it
  (a loss the run carries on from; a loss that ends the run goes in the `result`), what each kind and `by` mean, that
  unknown counts are left out, that an unlisted kind is `other` with a message and an issue filed, and the SDK helper.
  Verify the doc's links resolve with the repository's docs check.
- [x] 4.2 Regenerate the event reference (`uv run scripts/docs_reference.py`) so `docs/prompt-book/events.md` lists
  the `context` event, and verify its check mode passes.

## 5. Integration

- [ ] 5.1 Run `uv run scripts/check.py` and verify it passes, with the full test run on all three platforms in CI
  once the pull request is marked ready.
- [x] 5.2 Check that release-please will release this as a protocol and SDK `feat` (design D8): every commit is a
  `feat` or `docs` with no `!`, and release-please assigns a commit to each component whose path it touches. Verified
  with `git log --format=%s origin/main..` and `git log origin/main.. -- <path>` against `release-please-config.json`:
  `9da8886` (`feat(runner-protocol):`) touches `protocol`, `troupe-plugin-sdk`, `troupe` and `troupe-runner-scripted`,
  so each gets a minor bump. The SDK's part shares that commit's `runner-protocol` scope, as D8 says.

## Workflow follow-up

- If #296 (`failure-reason`) merges first, rebase on it, resolve the shared lists, run the full check, and fix in a
  new commit.
- Archive with `/opsx:archive` on the branch after the review of the last push is clean.
- After the merge, comment on #307 with the PR and the archived change, close it if the PR didn't, and check its card
  says Done. #308 and #310 then send the event.
