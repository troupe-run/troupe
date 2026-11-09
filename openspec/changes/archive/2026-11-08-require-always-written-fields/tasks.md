# Tasks

Each group's schema commit is a breaking Conventional Commit (`feat(protocol)!: ...`, design D6). After any schema
edit, regenerate the packaged copy with `uv run scripts/package_schemas.py` and the events reference with
`uv run scripts/docs_reference.py`, in the same commit.

## 1. `init.effects` is required wherever an init is read

- [x] 1.1 Before changing anything, write the new tests and run them on the current code to see them fail: an init
  without `effects` fails `run-event.schema.json#/$defs/hostEvent`, fails `InitEvent.from_data` naming `effects`, and
  fails `LoggedEvent` in a client message (runner-protocol delta, "A recorded init without it"). Verify each fails on
  the current code for the stated reason.
- [x] 1.2 In `protocol/schemas/runner/run-event.schema.json`, add `effects` to `$defs/init`'s `required`, make
  `$defs/event` refer to `init` directly, and drop the older-init sentences from `hostEvent`'s and `effects`'
  descriptions (D1). Verify 1.1's schema tests pass, `test_runner_types.py`'s test that `$defs/event` refuses an init
  without `effects` still passes, and `uv run scripts/package_schemas.py --check` is clean.
- [x] 1.3 In `packages/troupe-plugin-sdk/src/troupe_plugin_sdk/runner.py`, make `InitEvent.effects` required (no
  default, above `engine`), update its docstring, and remove `parse_event`'s separate check (D1). Remove the SDK test
  that an init without `effects` reads as a host event, and the query test in `test_run_queries.py` that a recorded
  one still reads. Verify 1.1's SDK tests pass, `parse_event` still refuses a runner's init without `effects` with
  "missing required field 'effects'", and `uv run pytest packages/troupe-plugin-sdk plugins` passes. No runner code
  changes: every runner already sends it.

## 2. `Run.Started` holds what troupe writes now

- [x] 2.1 Write the new schema tests first and run them on the current code to see them fail: a start without
  `workspace`, one with `runner_reported`, and a worktree start with `clones` in its workspace each fail
  `run-started.schema.json` (runs delta, "A start without its workspace", "A start that holds clone mechanisms", "A
  start that names the reported runner"). Verify each fails on the current code.
- [x] 2.2 In `run-started.schema.json`, add `workspace` to `required`, remove `runner_reported` and the worktree
  workspace's `clones`, and say in `runtime`'s description only that an actor named no runtime. Move `$defs/clones` to
  `run-worktree-made.schema.json` and drop "or its start was recorded by an older troupe" from its description (D2,
  D3). Verify 2.1's tests pass.
- [x] 2.3 In `client/run.schema.json`, give the summary its own `$defs/workspace` and `$defs/worktreeWorkspace` (each
  field a `$ref` to the start's worktree workspace, plus `clones` from `run-worktree-made`), and point the summary's
  `workspace` and its worktree condition at them (D3). Verify `test_client_schemas.py`'s worktree cases (with clones
  once made, without before) pass, and `test_client_messages.py`'s property test passes.
- [x] 2.4 In `core/runs/aggregate.py`, make `workspace` a required argument of the `Started` event and remove
  `runner_reported`. In `core/runs/projections.py`, read the workspace with no theatre fallback, add
  `Run.WorktreeMade`'s clones to a worktree whenever recorded, and take the reported runner only from the init. Update
  the module docstrings that describe the older troupe's start (D2, D3). Verify `mypy --strict` is clean, and
  `test_run_aggregate.py`, `test_event_payloads.py`, `test_run_queries.py`, `test_run_workspaces.py` and
  `test_perform.py` pass once their old-shape starts are rewritten or removed as design D7 lists.
- [x] 2.5 Remove `test_run_changes_recording.py`'s run that leaves out its workspace "as every run recorded before
  this change did": the start `perform` records is covered by the file's other tests. Verify the file passes, and
  `grep -rn "recorded before this change\|older troupe" packages/troupe/tests` finds only the actor re-check in
  `test_perform.py` (proposal, "Not changed").

## 3. The audit is required wherever the runner started

- [x] 3.1 Write the new tests first and run them on the current code to see them fail: an end with ending `exited` or
  `killed` and no `outcome.audit` fails `run-ended.schema.json`; an ended summary with a `transcript` and no `audit`
  fails `client/run.schema.json` and `RunSummary.from_data`, naming `audit`; an ended summary with no `transcript`
  and an `audit` fails both (runs and client-protocol deltas). Verify each fails on the current code.
- [x] 3.2 In `run-ended.schema.json`, add `audit` to the runner-started branch's `required` and drop "or the end was
  recorded before troupe recorded audits" from its description (D4). In `client/run.schema.json`, add the rule to the
  `state is ended` branch's `then` and drop the same phrase from the summary's `audit` description (D5). Verify 3.1's
  schema tests pass.
- [x] 3.3 In `core/client/messages.py`, add to `RunSummary._check` that an ended summary has `audit` exactly when it
  has `transcript` (D5). Update `RunOutcome.audit`'s docstring in `core/runners/outcome.py` to say `perform` always
  audits (D4). In `test_client_messages.py`, make the summary generator draw `audit` for an ended summary exactly when
  it drew `transcript`. Verify 3.1's message tests pass, and the property test passes over its full example count.
- [x] 3.4 Remove `test_run_changes_recording.py`'s end recorded with no audit "as every end recorded before this
  change", and make every other end fixture whose runner started but has no audit carry one (including
  `test_cli_runs.py`'s audit-error summary, checked with `RunSummary.from_data`). Verify
  `uv run pytest packages/troupe` passes.

## 4. Nothing else keeps a form for older records

- [x] 4.1 Search again with
  `grep -rn -i -E "recorded before|older troupe|before (runs|runners|audits|runtimes)" protocol/schemas packages/*/src plugins docs contributing`
  and check that each remaining hit is about order in time (such as "recorded before its runner starts") or the actor
  re-check, not a form kept for old records. (`contributing` was added after Claude's review found
  `contributing/runners.md` and `contributing/runs.md` still describing the removed forms; both are fixed.) Verify
  `docs/prompt-book/events.md` no longer lists `runner_reported` and says `workspace` is required, and
  `uv run scripts/docs_reference.py --check` is clean.
- [x] 4.2 Raise the issue design D5 names (a run summary's `transcript` and `stderr` aren't forbidden by the schema
  on a run that hasn't ended), with `--project "troupe roadmap"`, citing #305. Verify it's on the board with
  `gh issue view <n> -R troupe-run/troupe --json projectItems`.

## 5. Integration

- [x] 5.1 Run `uv run scripts/check.py`. Verify it passes, including the packaged-schema, docs-reference and
  protocol-guard checks, and `openspec validate require-always-written-fields --strict`.
- [x] 5.2 Once the pull request is ready, verify CI's legs pass on Linux, macOS and Windows on the last code commit,
  and cite the run.
  Passed: CI run 42378210814 on `fbfcfed`, the last code commit (all 12 legs, Linux, macOS and Windows on Python
  3.12 to 3.15).

## Workflow follow-up

- Act on Claude's review of the last push, archive the change on the branch, and ask the owner to merge.
- After the merge, comment on #305 with the PR and the archived change, check it's closed and its card is Done.
