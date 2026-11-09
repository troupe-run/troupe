# Tasks

## 1. Pin down today's behaviour before changing it (design D9, Risks)

- [x] 1.1 Run the host's and Claude Code's byte-for-byte transcript tests (`test_run_host.py`, `test_claude_fixtures.py`,
  and the Claude Code runner's fixture tests) on the unchanged code, and note which tests prove native storage, so
  they can be run unchanged after group 4. Verify: the test run's pass counts and the list of those tests are in the
  first apply commit's message. Baseline 2026-11-07: `test_run_host.py`,
  `test_claude_fixtures.py`, `test_claude_code_runner.py` and `test_claude_code_mapping.py`: 180 passed.
- [x] 1.2 Check what today's host does with a transcript record holding a lone surrogate escape (`"\ud800"`), as the
  Ollama runner can send. Use a scripted `rawStdout` line in a throwaway test. If the host fails on it (anything but
  storing it or a protocol violation), file a Bug issue on the board (`--project "troupe roadmap"`) and name it in the
  PR. Don't fix it in this change unless framing makes it worse. Verify: the observed behaviour, and the issue number
  if one was filed, are in the commit message for 1.1 or noted in this task. Observed 2026-11-07: the host
  raises an unhandled `UnicodeEncodeError` at `record.record.encode()`, and the scripted runner aborts (exit -6) on a
  surrogate step. Filed as #311; framing uses the same conversion, so this change leaves it as it is.

## 2. The contract's schemas (spec: runner-protocol, runs, client-protocol; design D2–D4)

- [x] 2.1 `protocol/schemas/runner/run-transcript.schema.json`: add `kind` (`enum: ["sent", "received", "note"]`), its
  description saying what each kind is and what absence means. Update the schema's description, which says records
  are only native output. Verify: a test validating examples shows a record with each kind and one without validate,
  and kind `request` doesn't.
- [x] 2.2 `protocol/schemas/runner/initialize.schema.json`: make the capability names in the request and the result
  `enum: ["transcript-kinds"]`, and replace "Version 0 defines none" with what `transcript-kinds` means. Verify: a test
  shows an answer naming `transcript-kinds` validates, and one naming `widgets` doesn't.
- [x] 2.3 Add `protocol/schemas/transcript-record.schema.json`: one stored line of a transcript whose run used kinds
  (`kind` and `record` required, `encoding` only `base64`, closed). Add its row to `protocol/README.md`'s table.
  Verify: `test_protocol_strict.py` passes and covers the new file, and an example line validates while one with
  `"encoding": "utf-8"` or an extra key doesn't.
- [x] 2.4 `protocol/schemas/events/run-ended.schema.json`: add `transcriptFormat` (`native`, `kinds`), carried by the
  existing `ending` rule: required with any ending but `never-started`, which forbids it as it forbids `transcript`
  (design D4). Verify: the runs spec's scenarios as schema tests (a transcript without its format doesn't validate,
  `never-started` with a format doesn't, the format without a transcript doesn't).
- [x] 2.5 `protocol/schemas/client/run.schema.json`: add `transcriptFormat` to the run summary, with `transcript` and
  `transcriptFormat` each requiring the other. Verify: a schema test shows a summary with one and not the other
  doesn't validate.
- [x] 2.6 Run `uv run scripts/package_schemas.py` and the docs reference generator (`scripts/docs_reference.py`, which
  renders the event reference), and check any generated models (`scripts/generate_models.py --check`). Verify: each
  script's `--check` passes, and the diff is only the new fields and file. Done 2026-11-07: `package_schemas.py` copied the schemas; the events reference lists only
  top-level payload fields, so `docs_reference.py --check` passes with no change; `generate_models.py --check` passes.

## 3. The plugin SDK (design D8)

- [x] 3.1 In `troupe_plugin_sdk/runner.py`, add `TRANSCRIPT_KINDS` and `CAPABILITIES`, give `TranscriptRecord` an
  optional `kind` checked against `TRANSCRIPT_KINDS`, and make `InitializeParams` and `InitializeResult` refuse a
  capability not in `CAPABILITIES`. Verify: SDK tests show a record with each kind round-trips through
  `from_data`/`to_data`, an unknown kind and an unknown capability are `ProtocolError`s naming the field, and the
  SDK's types still agree with the schemas in the schema-agreement test.

## 4. The host offers, enforces and frames (spec: actor-runners, runner-protocol; design D2, D3)

- [x] 4.1 Offer `transcript-kinds` (`OFFERED_CAPABILITIES`) and keep, for the run, whether the runner accepted it.
  Verify: a host test shows troupe's `initialize` offers `transcript-kinds`, using the scripted runner, which records
  what it was offered.
- [x] 4.2 Refuse a record with a kind in a run without kinds, and one without a kind in a run with them, as protocol
  violations that store nothing. Drive it with the scripted runner with and without `--transcript-kinds` (group 6
  lands the flag first if needed). Verify: both runner-protocol violation scenarios pass, and the stored transcript
  holds only the records before the violation.
- [x] 4.3 In a run with kinds, write each record as D3's framed line, after masking, keeping the runner's encoding, and
  count the stored bytes against `transcript_max_bytes`. Verify: the actor-runners scenarios pass (a sent and a
  received record, a base64 record, the credential in a framed record, framing passing the limit). Add a hypothesis
  property test: for arbitrary text and byte records, each with a kind and with or without the credential embedded,
  every stored line validates against `transcript-record.schema.json` and decodes back to the masked bytes.
- [x] 4.4 Re-run 1.1's native tests unchanged. Verify: the same tests pass with the same counts, so a run without
  kinds stores the same bytes as before. Done 2026-11-07: the same four files, 191 passed (the 180 of 1.1 plus this change's new host
  tests).

## 5. The run's end and its summary (spec: runs, client-protocol; design D4)

- [x] 5.1 Carry `transcriptFormat` in the run outcome (`outcome.py`) beside `transcript`, and record it in `Run.Ended`.
  Verify: a perform test records `kinds` for a scripted run with `--transcript-kinds`, and `native` for one without.
  Each recorded end validates against its schema.
- [x] 5.2 Project it into the run summary (`runs/projections.py`, `client/messages.py`), and show `(kinds)` after the transcript's reference in `troupe status` (`cli/render.py`). Verify: a
  projection test shows the summary's format is the end's, for each format, and a render test shows `(kinds)` only for
  `kinds`.

## 6. The scripted runner (spec: scripted-runner; design D7)

- [x] 6.1 Add the `--transcript-kinds` flag (accept the capability when offered, otherwise none) and `kind` on a
  transcript step's object form, checked against the SDK's `TRANSCRIPT_KINDS` and sent as given. Add `kind` to the
  published options schema. Verify: the scripted-runner scenarios pass as runner tests (with and without the flag, a
  step with a kind, kind `request` refused with `scripted.invalid-script`), and the options schema passes the
  strictness check.

## 7. The OpenAI runner (spec: openai-runner; design D5)

- [x] 7.1 Change `exchange.py`'s record calls to `(kind, data)` with D5's mapping: request body `sent`, stream line
  and error body `received` (bytes, base64 when not UTF-8), status with kept headers and a dropped stream as `note`.
  Drop the URL. Verify: `test_openai_exchange.py` asserts each record's kind and bytes for a success, a 429 with a
  body, a non-UTF-8 error body and a broken stream.
- [x] 7.2 In the runner, accept `transcript-kinds` when offered and add `kind` to records only then. Mask a base64
  record's bytes before encoding them. Verify: runner tests show the answer and records with the capability offered
  and without it (same records, no kind), and the canary-credential scan still finds no credential, a non-UTF-8
  error body holding the canary included.
- [x] 7.3 Update the runner's D10 references (docstrings, `defaults.py`'s header note) to the contract's kinds, and the
  fixtures' expected transcripts if they hold any. Verify: `uv run pytest plugins/runner-openai` passes, and searching
  the plugin for `"kind": "request"` finds nothing.

## 8. The Ollama runner (spec: ollama-runner; design D6)

- [x] 8.1 Give `Sink.transcript` a kind: the first request's body and added messages `sent`, answer lines and error
  bodies `received`. In the runner, accept `transcript-kinds` when offered and add `kind` only then. Verify: the
  ollama-runner scenarios pass (each record's kind, an error body, with and without the capability), and the records'
  bytes and order are unchanged from main in the existing conversation tests.
- [x] 8.2 Regenerate the fixtures' `transcript.jsonl` with `fixture_replay`'s writer so they hold each record's kind.
  Verify: `uv run pytest plugins/runner-ollama` passes, and the fixture diff changes only the added kinds. Done 2026-11-07: every regenerated line's record equals the old line, in order (checked by
  script against a copy taken first), and `events.json` didn't change.

## 9. Documentation and integration

- [x] 9.1 Update `contributing/runners.md`: "The transcript" (kinds, the capability, the stored form, the run's end
  naming it), the message table's `run/transcript` and `initialize` rows, and "A run goes like this" step 1, which says
  version 0 defines no capabilities. Verify: each changed statement matches the specs, and the doc build or link check
  `scripts/check.py` runs passes.
- [x] 9.2 Run the conformance check (`test_runner_conformance.py`) for every runner, and `uv run scripts/check.py`.
  Verify: both pass locally. CI on Linux, macOS and Windows passes on the pull request's last code commit, cited
  here by run id. Done 2026-11-09: conformance 10 passed (1 opt-in skip); `scripts/check.py` passed on the rebased
  branch. CI run 42546733027 on `725b7ed2`, the last code commit, passed on all twelve legs (Linux, macOS and
  Windows, Python 3.12 to 3.15); its one failure on the first attempt, `check (ubuntu-latest, Python 3.14)`, was the
  known flake #301 and passed on re-run (attempt 2).

## Workflow follow-up

- Open a draft pull request that closes #294, act on Claude's review of the last push, then mark it ready.
- Archive the change on the branch before merging (`/opsx:archive`). The owner merges.
- After the merge, comment on #294 with the PR and the archived change, and check its card says Done.
