# Tasks

## 1. The protocol: a recorded notice, the log, and a recording that failed on a notice

- [ ] 1.1 Add `protocol/schemas/events/run-noticed.schema.json` (closed: `lineage`, `timestamp`, `notice` referencing
  `../notice.schema.json`), and select it by the topic `troupe.core.runs.aggregate:Run.Noticed` in
  `event-record.schema.json` everywhere `Run.Reported` is listed (D1). Verify `test_event_payloads.py` gains a valid
  `Run.Noticed` payload and refuses one without `notice` or with an extra field, and `test_event_schemas.py`'s
  every-topic-has-a-schema check fails until `TOPICS` has the topic (task 2.1) and passes after.
- [ ] 1.2 Make `recording` in `events/run-ended.schema.json` a `oneOf` of `{failedAt, error}` and `{notice, error}`,
  `notice` a notice code, each closed, with both descriptions saying what each names (D5). Verify
  `test_event_payloads.py`: an end recording a notice validates, one with both `failedAt` and `notice` or neither
  doesn't, and an end with `failedAt` still does.
- [ ] 1.3 In `client/run.schema.json`, add `$defs/loggedNotice` (`kind` `run-notice`, `runId`, `at`, `notice`; no
  `seq`), the summary's `notices` (array of closed `{at, notice}`, `minItems` 1), and the summary's `recording` as the
  same `oneOf`; change `logs-result.schema.json`'s `events` to `log` (items `oneOf` `loggedEvent`, `loggedNotice`, in
  recorded order) and add `loggedNotice` to `logs-update.schema.json`'s `oneOf` (D8). Regenerate the packaged copies
  with `uv run scripts/package_schemas.py`. Verify `test_client_schemas.py` covers each client-protocol delta
  scenario: a summary with one notice validates, an empty `notices` doesn't, a `run-notice` entry with a `seq`
  doesn't, a `recording` with both or neither doesn't; and the protocol strictness check in `scripts/check.py` passes.
- [ ] 1.4 Mirror the schemas in `core/client/messages.py`: `LoggedNotice`, `RunNotice` (`at`, `notice`),
  `RunSummary.notices`, `LogsResult.log` (replacing `events`), the logs update union, and the recording's `notice`.
  Verify `test_client_messages.py` round-trips each through `from_data`/`to_data` against the schemas, and refuses a
  `null` `notices`.
- [ ] 1.5 Regenerate `docs/prompt-book/events.md` and any other generated reference with
  `uv run scripts/docs_reference.py`. Verify `uv run scripts/docs_reference.py --check` passes and `Run.Noticed` has
  its own section.

## 2. Recording: the aggregate and the recorder

- [ ] 2.1 In `core/runs/aggregate.py`, add `Run.notice(data)` recording `Run.Noticed`, refused with
  `run.out-of-sequence` after the end, leaving `next_seq` alone; add `NOTICED` to `TOPICS`, and describe the event in
  the module docstring (D1). Verify `test_run_aggregate.py`: a notice between the start and the end is recorded and a
  following event with the next `seq` is still accepted; a notice after the end is refused and the stream unchanged
  (runs delta, "recorded only between its start and its end").
- [ ] 2.2 In `core/runs/perform.py`, give `_Recorder` the FIFO queue and single writer task (D3): `notice()` masks the
  notice with the run's credential masker (D7), sends it live at once and queues it; entering from another thread goes
  through `call_soon_threadsafe`; the writer starts once the start is recorded; `on_event` queues and awaits its entry;
  `end` and `_could_not_start` wait for the queue to empty first. Route `announce` and `on_announce` to
  `recorder.notice` from the moment the run id is minted, creating the recorder before `plan_worktree` (D2). Record
  each `Run.Noticed` through the person's command (D4). Verify in `test_perform.py`, with the scripted runner: the
  runs delta's "A silence and a retry are kept" stream order and live updates; "A notice raised before the start" for
  a dirty theatre; "A notice raised after the runner ends" with a scratch directory that can't be removed; the
  lineage scenario; and that a `config.file-rewritten` raised before the run isn't recorded.
- [ ] 2.3 Add a recorder test that raises notices from a timer thread and from the event loop while run events are
  recorded, and checks every notice is recorded exactly once, in the order each reached the loop, before the end, with
  each run event still recorded before its `LoggedEvent` update is sent. Verify it passes on all three CI platforms
  (it runs in the normal suite).
- [ ] 2.4 Make a notice that can't be recorded a recording failure (D5): `failure` holds the notice's code or the
  event's `seq`, the run is cancelled, nothing later is recorded but every notice is still sent, the end's
  `recording` names `notice` or `failedAt`, and `_recording_failed` and `_recording_details` name whichever failed
  first. Verify in `test_perform.py`, with a store that refuses the first `Run.Noticed`: the runs delta's "The store
  refuses a notice" and "A notice fails to record and the end is recorded"; and that the existing "only the end fails"
  and `seq` 2 tests pass unchanged apart from asserting no `notice`.
- [ ] 2.5 Add a masking test: a notice whose problem holds the run's credential is recorded and sent with
  `[credential]` in its place. Verify it fails with `recorder.notice`'s masking removed.
- [ ] 2.6 Update `contributing/runs.md` (the `Run.Noticed` row in the events table, who records it, which notices are
  a run's, and the rule that a new run notice that can repeat states its bound, D6) and `contributing/event-store.md`
  (the topic's row). Verify `test_runs_doc.py` and the docs link checks pass.

## 3. Reading back: status and logs

- [ ] 3.1 In `core/runs/projections.py`, fold `Run.Noticed` into `RunView.notices` always and, with `keep_log`, into
  `log` as a `LoggedNotice` in stream order; the summary carries `notices` only when there are any (D8). Verify in
  `test_run_queries.py`: the runs delta's "Status of a run that raised notices", "Status of an interrupted run that
  raised a notice", a run with no notices has no `notices`, and the summary validates against the run schema.
- [ ] 3.2 In `core/runs/queries.py`, return `LogsResult.log`, and have following send recorded notices as
  `run-notice` updates as they're recorded. Verify in `test_run_queries.py`: "Logs of a run that raised a notice"
  returns the four entries in order, and a follower started before a run falls silent receives the `run.silent`
  update among the events and before the end (runs delta, "Following shows a notice as it is recorded"); the existing
  following timing test passes unchanged.

## 4. The CLI

- [ ] 4.1 In `cli/render.py` and `cli/commands.py`, show recorded notices (D9): `render_run`'s notices lines,
  `render_run_line`'s count, and `troupe logs` printing `run-notice` entries and updates on standard output among the
  events, derived notices staying on standard error. Verify in `test_cli_runs.py` each cli delta scenario: status of
  a run that fell silent, the list's count on only the run with notices, logs of a run that retried in order, a
  followed silence, no notice line for a run without, and an interrupted run's `run.silent` on standard output with
  `run.interrupted` on standard error.
- [ ] 4.2 Update `docs/the-company/performances-and-runs.md` (the `Run.Noticed` event, and that status and logs show
  a run's notices afterwards) and regenerate the CLI reference if its text changed. Verify
  `uv run scripts/docs_reference.py --check` and the user-docs tests (`test_user_docs_*.py`) pass.

## 5. Integration

- [ ] 5.1 Run `uv run scripts/check.py`. Verify it passes: mypy --strict, ruff, every test, the protocol checks and
  the generated-docs checks.
- [ ] 5.2 Perform a real run end to end in a scratch theatre with the scripted runner set to fall silent past a
  lowered silence threshold and to retry once, without watching it, then run `troupe status <run>` and
  `troupe logs <run>` from another shell. Verify both show the `run.silent` and `run.retrying` notices, and paste the
  output in the PR.
- [ ] 5.3 Search the org's other repositories for readers of the `logs` result's `events` field
  (`gh search code` for `logs-result` and `"events"` with `troupe logs --json`). Verify none is found, or each is
  listed in the PR with an issue raised for it.
- [ ] 5.4 Check PR #317 (`estimated-cost`): if it merged first, rebase and add a `test_perform.py` case where a
  runner sends an estimate with no price and the `run.estimate-dropped` notice is in the run's stream before the
  result event; if this merges first, comment on #317 asking for the same case on its rebase (D10). Verify the test
  or the comment exists.

## Workflow follow-up

- Open the draft PR (`Closes #327`), act on Claude's review of the last push, mark it ready, and archive the change
  on the branch before the owner merges.
- After the merge, comment on #327 with the PR and the archived change, and check the roadmap card says Done.
