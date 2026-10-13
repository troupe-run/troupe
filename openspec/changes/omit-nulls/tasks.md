# Tasks

## 1. The rule in the walker

- [x] 1.1 Add the null rule and the `x-troupe-null` marker to `tests/strictness.py` (design D1): `x-troupe-null` is
  a value keyword; on accepting nodes (not inside `if`/`not`) report an unmarked null (`type` string or list,
  `const`, `enum`), a stray marker and a malformed marker. Add one `test_protocol_strict.py` fixture per case
  (four null forms, marker with unknown kind, empty `means`, extra field, stray marker) asserting the rule and JSON
  Pointer, plus one accepting a marked null and one accepting `{"not": {"type": "null"}}`. Verify those tests pass
- [x] 1.2 Add the optional-property description rule (design D2) with a bad-schema fixture (a property not in
  `required` with no `description`) and a good one (the same with a description, and a required property without
  one). Verify they pass
- [x] 1.3 Run the walker over every shipped schema and record its findings: mark the shipped-schema strictness test
  `xfail(strict=True)` with the reason "nulls and undescribed optional fields on main, closed by groups 2 to 6".
  Verify it xfails and that the null findings are exactly the 33 nodes in design Context (32 from #76 plus
  lineage `stage`), and record both lists for the PR
- [x] 1.4 Add a description to each of the 39 optional properties the walker reports (design D2), each saying what
  absence means; print the list of property → description for review. Verify the walker reports no description
  finding for any schema, and `test_runner_schemas.py`, `test_client_schemas.py` and `test_event_schemas.py` pass
- [x] 1.5 State the rule in the protocol: a "Nulls and absent fields" section in `protocol/README.md` (absence is
  "nothing to say", meaningful values over absence, no sentinels, the marker and its two kinds, the one external
  exception). Verify the README's schema table still matches the files (`test_protocol_strict.py`'s README check, or
  by listing both)

## 2. Lineage

- [ ] 2.1 `lineage.schema.json`: `reason`, `stage`, `vcs.branch`, `vcs.head`, `vcs.source`, `source.before`,
  `source.after` leave `required` and lose their null branches; `stage`'s enforced branch has no `allowedBy` (D3);
  descriptions say what absence means, and the "absent is explicit" wording goes (D6). Verify the walker reports no
  finding in `lineage.schema.json`
- [ ] 2.2 `core/events/lineage.py`: `to_data` methods leave out `None` fields; `lineage_problem`, `_vcs_problem` and
  `_stage_problem` accept absence and refuse `null` naming the field. Verify `test_lineage_types.py`, updated:
  every shape built validates against the schema, no-reason / no-stage / plain-filesystem / detached / new-file
  shapes have no such key, and each of `reason`, `stage`, `stage.allowedBy`, `vcs.branch`, `vcs.head`,
  `vcs.source`, `before`, `after` set to `null` is refused with `events.lineage-invalid` and writes nothing
- [ ] 2.3 Update the lineage table in `docs/event-store.md` (`reason`, `stage`, `vcs`: left out when absent, and
  what that means). Verify `test_event_store_doc.py` passes

## 3. Event store: segment header and the event-field rule

- [ ] 3.1 `event-record.schema.json` header: `branch` optional with its absence described. `codec.py`:
  `encode_header` leaves out `None`; `_header` accepts `{session, vcs}` or with a non-empty `branch`, and refuses
  `"branch": null` as `events.malformed-record`. Verify store tests: a detached-HEAD session's header has no
  `branch`, a header with `"branch": null` fails naming file and line, and every header line validates
- [ ] 3.2 `notice.schema.json` `events.other-branch`: `branch` optional; `store.py` leaves it out when the header has
  none. Verify a store test on a branchless uncommitted segment gives a notice whose details have no `branch` and
  validate (the guard checks it)
- [ ] 3.3 `EventStore._stored` removes top-level `null` keys from the state (design D4), and a test walks every
  aggregate's `@event` methods and `__init__` asserting each parameter typed `X | None` defaults to `None`. Verify
  that test passes and fails when a default is removed (run it once against a temporary edit)

## 4. Runs: start, end and recording failure

- [ ] 4.1 `events/run-started.schema.json`: `runner_reported` optional, absence described. `Run.__init__`:
  `runner_reported` defaults to `None`. `projections.py` reads it with `.get`. Verify a perform test where the
  runner exits before init: the recorded start has no `runner_reported`, validates, and the aggregate loads back
- [ ] 4.2 `events/run-ended.schema.json`: `recording` optional; outcome `error` and `result` optional; `exitCode`,
  `transcript`, `stderr` tied to `ending` by `if`/`then`/`else` (D3). `Run.end`/`_ended`: `recording` defaults to
  `None`. `RunOutcome.to_data` leaves out `None`. Verify: schema tests that an `exited` end without `exitCode` and a
  `never-started` end with a `transcript` don't validate; perform tests for a never-started run (error, no
  exit code/transcript/stderr/result/recording) and a succeeded run (exit code 0, transcript, stderr, result, no
  error/recording), both validating and loading back
- [ ] 4.3 `error.schema.json`: `runner.crashed` and `run.unclean-exit` `exitCode` tied to `ending`;
  `run.recording-failed` `failedAt`, `endError`, `transcript` optional. `outcome.py` and `_recording_failed` leave
  out `None`. Verify `test_run_outcome.py` and `test_perform.py`: end-only failure has `endError` and no
  `failedAt`; seq-2 failure with a recorded end has `failedAt` 2 and no `endError`; every error validates (guard)
- [ ] 4.4 `notice.schema.json` `run.retrying`: `maxAttempts` optional. `host.py` leaves it out when the runner
  didn't say. Verify a run-host test with a `retry` event without `maxAttempts` gives a notice with no
  `maxAttempts` that validates
- [ ] 4.5 Verify the event-store spec's scenario end to end: a test records a run whose runner can't start, reads
  its segment lines back, finds no `null` at any depth, and each payload validates by topic

## 5. Client protocol and CLI

- [ ] 5.1 `client/run.schema.json` summary: `outcome`/`endedAt` tied to `state` (D3); `error`, `transcript`,
  `stderr`, `recording`, `runner.reported` optional with absence described. Verify schema tests: `interrupted` with
  an `outcome`, and `ended` without `endedAt`, don't validate
- [ ] 5.2 Remove `nullable` from `json_field` and `_decode` (`core/messages.py`); the eight fields in
  `core/client/messages.py` become `default=None`. Verify `test_client_messages.py`: a summary for a running run has
  no `outcome`/`endedAt`; an ended one has both; reading a summary with any of the eight fields `null` fails naming
  the field
- [ ] 5.3 `cli/render.py` and `cli/commands.py` read optional summary fields with `.get`. Verify `test_cli_runs.py`:
  `status` for a running run, and `perform` for a never-started run, render as before, and `--json` output has no
  `null` and validates against the client schema
- [ ] 5.4 `cli/parser.py` leaves out `suggestion` when there is none. Verify a CLI test of an unknown command with
  no close match: the error's details have only `command`, and validate

## 6. Runner contract: the one marked null

- [ ] 6.1 `runner/error-response.schema.json` `id`: the null branch carries
  `"x-troupe-null": {"kind": "external", ...}` (D1). Verify a scripted-runner test sends an unparseable line, gets
  `runner.parse-error` with `"id": null`, and the reply validates; and a refused readable request carries its id
- [ ] 6.2 Remove the `xfail` from the shipped-schema strictness test. Verify it passes, with the error-response `id`
  as the only node accepting `null`

## 7. Whole change

- [ ] 7.1 Search `packages/` and `plugins/` sources for `None` written into payload dicts (`: None`, `else None`
  inside `details=` / `to_data`) and confirm each remaining one is not serialised; list them in the PR. Verify by
  the search output
- [ ] 7.2 Run `uv run scripts/check.py`. Verify it passes (ruff, mypy --strict, the full test suite)
- [ ] 7.3 Push and verify every CI job passes on Linux, macOS and Windows

## Workflow follow-up

- Open the PR with `Closes #76`, listing the walker's before/after findings (1.3), the descriptions added (1.4) and the
  remaining `None`s (7.1).
- Run `/opsx:archive` on the branch before merging.
- After the merge, comment on #76 with the PR and the archived change.
