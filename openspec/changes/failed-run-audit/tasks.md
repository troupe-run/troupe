# Tasks

## 1. The protocol: the audit in the run's end and the summary

- [x] 1.1 Add `$defs/audit` to `protocol/schemas/events/run-ended.schema.json` (a `oneOf` of closed `{outside: [...]}`,
  each entry `{path, change, needs, to?}` with `to` exactly for `moved`, and `{error}`), and `outcome.audit`
  referencing it, forbidden by the `never-started` branch and optional otherwise, with its absence described (D2).
  Verify `test_event_payloads.py` gains cases: an end with an empty `outside` validates, one with both `outside` and
  `error` or neither doesn't, a `never-started` end with an `audit` doesn't, and an end without one still does.
- [x] 1.2 Add `audit` to `protocol/schemas/client/run.schema.json#/$defs/summary`, referencing the event's
  `$defs/audit`, and regenerate the packaged copies with `scripts/package_schemas.py`. Verify `test_client_schemas.py`
  covers a summary with an audit, and one whose audit has both `outside` and `error` failing (client-protocol delta),
  and that the protocol strictness check in `scripts/check.py` passes.
- [x] 1.3 Regenerate `docs/prompt-book/events.md` (and any other reference generated from these schemas) with
  `uv run scripts/docs_reference.py`. Verify the generated docs check passes and `Run.Ended`'s `outcome` row says it holds what the audit found
  (the reference lists only top-level fields).

## 2. The audit as its own port in the run host

- [x] 2.1 In `core/runners/effects.py`, add `AuditFindings` (`outside` or `error`, refusing both or neither), the
  `Audit` port and `NoAudit`; make `DeclaredEffects` an `Audit` whose `after()` returns its findings and catches a
  read failure into `error` (D1, D3); add the verdict made from findings, failing with `effects.outside-declared`
  exactly as now, or `effects.audit-failed`. Verify `test_effect_audit.py`: the existing scenarios give the same
  errors through the new verdict, an empty list passes, and a `before` or `after` reader that raises gives `error`.
- [x] 2.2 In `host.py`, take `audit: Audit` beside `effect`, call `audit.before()` with `effect.before()`, and
  `audit.after()` after the process ends whenever it started; combine its verdict with `effect.after()`'s for an `ok`
  result only. `RunOutcome` carries `audit` and `to_data()` writes it. Update every caller (`conformance.py`, the
  host, fixture and live tests) to pass `NoAudit()` explicitly. Verify `test_run_host.py` gains tests with a recording
  audit: an error result, a timeout, a cancel and a crash each return its findings with an unchanged outcome and
  error; a runner that never answers the handshake is audited; a missing command has no audit; an `ok` result with a
  change outside the declaration fails with `effects.outside-declared` and the same findings; an `ok` result with a
  failing read fails with `effects.audit-failed`; an error result with a missing expected file fails with
  `run.error-result` alone.
- [x] 2.3 Extend `test_run_outcome.py` with a property test: without an `ok` result, no effect or audit verdict
  (passed, missing file, outside the declaration, audit failed) changes `derive_outcome`'s outcome or error. Verify
  it passes, and fails when `derive_outcome` consults the verdict before an error result. (The host's side, passing
  no verdict for a non-ok result, is 2.2's error-result, timeout, cancel and crash tests.)

## 3. perform records it

- [x] 3.1 Split `perform.effect_check_for` into the expected files and the audit, and pass both to `run_actor` (D1).
  Verify `test_perform_audit.py` and `test_effects_done_when.py` still pass unchanged, and the run's end validates
  against `run-ended.schema.json` with `outcome.audit`.
- [x] 3.2 Add perform tests with the scripted runner, one per issue done-when: a worktree run that `writeFile`s
  `src/a.py` outside `write: ["out/**"]` and sends an `error` result; a run that writes `notes.md` with no effects and
  `hang`s past `RUN_TIMEOUT_SECONDS`; a theatre run whose actor declares `write: ["**"]`, `hang`s, has `README.md`
  removed by the test, and is cancelled. Verify each end records its outcome and error unchanged, and
  `outcome.audit.outside` names the file and effect; the worktree run's changes are kept (effects and runs deltas).
- [x] 3.3 Add perform tests for the rest of the runs delta: a run whose changes are all declared and fails records an
  empty `outside`; a run that succeeds records an empty `outside`; a run whose runner can't be started has no
  `outcome.audit` (asserted in `test_run_workspaces.py`'s worktree that fails to fill); a run whose workspace can't be read (a VCS whose `file_states` raises after the runner ends) still
  has its end recorded, with the audit's error, and an `ok` result fails with `effects.audit-failed`. Verify they pass.

## 4. The summary, status and logs

- [x] 4.1 Copy `outcome.audit` into the summary in `RunView.summary`, and add `AuditData` and `RunSummary.audit` in
  `core/client/messages.py`. Verify `test_client_messages.py`: a summary with an audit round-trips, one with both
  `outside` and `error` is refused naming the field, and an end recorded without an audit (a stored event from before
  this change) gives a summary with none (in `test_run_changes_recording.py`, which builds
  recorded runs by hand).
- [ ] 4.2 Render the audit in `render_run` and after `logs`'s outcome line (D4), with the theatre note for a run in
  the theatre. Verify `test_cli_runs.py` covers each cli delta scenario through `troupe status <run>` and
  `troupe logs <run>` on recorded runs: timed-out with `notes.md` added needing `write`, cancelled with `README.md`
  removed needing `delete`, failed with every change declared, theatre note, and no audit line for a run that never
  started.
- [ ] 4.3 Update `docs/the-company/performances-and-runs.md` ("How a run ends" and "Effects": the audit runs whatever
  the outcome, a failed run keeps its error, and status and logs show what it found) and `docs/prompt-book/cli.md`
  where it describes `status` and `logs` output. Verify `test_cli_docs.py` and the docs checks pass.

## 5. Integration

- [ ] 5.1 Run `uv run scripts/check.py` and verify it passes (tests, mypy --strict, ruff, schema and docs checks).
- [ ] 5.2 Run `openspec validate failed-run-audit --strict` and verify the change is valid.
- [ ] 5.3 Verify CI passes on Linux, macOS and Windows once the pull request is marked ready, and record the run.

## Workflow follow-up

- Open a draft pull request that closes troupe-run/troupe#272, act on Claude's review, then mark it ready.
- Archive the change on the branch before the owner merges.
- After the merge, comment on #272 with the PR and the archived change, check it's closed and its card is Done.
