# Tasks

## 1. Lineage: the system actor

- [x] 1.1 Add the `system` actor kind (`{kind, id}`, no source) to `protocol/schemas/lineage.schema.json`, run `uv run scripts/package_schemas.py`, and verify its `--check` test passes
- [x] 1.2 Teach `core/events/lineage.py` (`_actor_problem`, a `System` actor type and `actor_data`) and `core/client/messages.py`'s `ActorData` the `system` kind, leaving `core/identity.py`'s `Kind` as `human`/`agent` so no identity source can produce it; verify with unit tests that a system actor is accepted and that one with a `source` is refused with `events.lineage-invalid` (`tests/unit/test_event_schemas.py` cases included)
- [x] 1.3 Add the core's system actor builder (`core@<host>`, host through the platform seam) and a test pinning its id shape on the running host
- [x] 1.4 Update `docs/the-company/lineage.md` and `contributing/event-store.md` for the `system` kind and for filled-in approvals; verify the docs check passes

## 2. Config: approvers on the actor

- [x] 2.1 Add `core/gates.py` with the role names, the default `[troupe, director]` and `approvers_problems`; unit-test each rule (unknown name, empty, duplicate, `troupe` not first, not ending in `director`, set with `workspace: theatre`), including a hypothesis test that every list it accepts ends in `director` and starts with at most one `troupe`
- [x] 2.2 Add `approvers` to `protocol/schemas/config/actor.schema.json` (with a description), regenerate the packaged schemas and `core/config/models.py`, and verify both `--check` tests pass
- [x] 2.3 Call `approvers_problems` from `core/config/kinds.py`'s actor check; verify with integration tests that `troupe config set` refuses each case with `config.invalid` naming the path, that a hand edit of `approvers: [troupe]` is refused by the sweep, and that `'actors.tester.approvers=["director"]'` is recorded
- [x] 2.4 Set `approvers: ["director"]` on every audition in `core/audition.py`; update the pinned audition dicts and file checks in `tests/integration/test_init.py` and `test_cli_init.py`, and verify `test_init_unit.py` still finds every audition valid
- [x] 2.5 Regenerate `docs/prompt-book/config-schema.md` (`uv run scripts/docs_reference.py`) and verify `test_user_docs_reference.py` passes

## 3. Runs: recording approvers and the gate's events

- [ ] 3.1 Record `approvers: {value, source}` on a worktree run's `Run.Started`, resolved in `perform._from_config` (schema `events/run-started.schema.json`, required on worktree runs, absent in place); verify with tests for source `default`, `actor`, and none on a theatre run, and that `perform --rehearse` shows them
- [ ] 3.2 Add `Run.GatePassed`, `Run.CueRaised` and `Run.ChangesRejected`: payload schemas, the three lists in `event-record.schema.json`, the aggregate's `TOPICS`, and rows in `contributing/runs.md`; verify `test_event_payloads.py` and `test_runs_doc.py` pass
- [ ] 3.3 Enforce the after-end order in `core/runs/aggregate.py` (D4): one pass before a cue, one cue, then one settling event; while a cue is open only an approved acceptance or a rejection settles it, and a discard or an unapproved acceptance is refused with `run.waiting-at-gate`; verify with aggregate unit tests for each allowed and refused order
- [ ] 3.4 Fold the new events in `core/runs/projections.py`: the `waiting` and `rejected` states, the summary's `approvers` and `gate` steps, and the status query's `cues` (every open cue, whatever the limit); extend `client/run.schema.json` and the status result schema, and verify with projection tests and the client-schema tests

## 4. The gate

- [ ] 4.1 Factor accept's check-apply-record-remove steps out of `core/runs/changes.py` so the gate and accept share them under the settle lock; verify the existing accept and discard tests pass unchanged
- [ ] 4.2 Add `core/runs/gate.py`: for a run that ended `succeeded` with a diff, `[director]`-first records the cue in the end's batch; `troupe`-first applies and records the acceptance with troupe's approval, or records the pass and the cue in one batch; verify with integration tests for a clean keep, a conflict passing to `director`, and `[director]` raising a cue without touching the working tree
- [ ] 4.3 Call the gate from `perform` after the end; verify that failed, cancelled, uncaptured and no-change runs reach no gate, and that a run with `[director]` killed right after its end still has its cue (a test pinning D3's windows, including that a `troupe`-first run stopped before troupe's step is `pending` and accept settles it)
- [ ] 4.4 Refuse `accept` and `discard` (and their rehearsals) on a run with an open cue with `run.waiting-at-gate`, naming the role and the approve or reject command; catalogue the code (`errors.py`, `error.schema.json`, `contributing/runs.md`) and verify with tests that nothing changes
- [ ] 4.5 Add the `approve` and `reject` core methods (client-protocol request/result schemas, `messages.py`, `core/runs/__init__.py`, `dispatch.py`'s `FAMILIES`, `tests/client_schemas.py`): approve keeps through the shared steps with the person's approval in role `director`, reject removes the worktree and records `Run.ChangesRejected`; both rehearse; verify with integration tests for each gates-spec scenario, including two approves at once
- [ ] 4.6 Add `gate.no-cue` and `gate.not-a-holder` (refusing an `agent` identity), and `rejected` in `run.changes-settled`'s details; catalogue them and verify with tests that raise each one, so `protocol_guard` passes

## 5. CLI

- [ ] 5.1 Add `ExitCode.WAITING = 4` and return it from `perform` when the work waits at a gate; verify with CLI tests for exit 4 (waiting) and 0 (kept), and regenerate the exit-code table
- [ ] 5.2 Replace `_settle_hint` with the end-of-run lines for kept, waiting and pending; verify with CLI tests for each perform-end scenario in the cli spec
- [ ] 5.3 Add `troupe approve` and `troupe reject` to `cli/table.py` and `cli/commands.py`, with `--reason` and `--rehearse`; verify with CLI tests, including the CLI stand-in core tests, and regenerate `docs/prompt-book/cli.md`
- [ ] 5.4 Render the open cues before the runs in `troupe status`, the `waiting` state with its role in run lines, and the approvers and gate steps in `troupe status <run>` and `troupe logs <run>` (`cli/render.py`); verify with rendering tests for each cli and runs spec scenario
- [ ] 5.5 Update `troupe init --audition`'s perform note (`cli/init.py`) to name `troupe diff`, `troupe approve` and `troupe reject`; verify with the init CLI tests, and that the printed steps' perform exits 4

## 6. User docs

- [ ] 6.1 Rewrite the first run's "Keep it, or not" in `docs/opening-night/first-performance.md` (and any matching text in `first-theatre.md` and `docs/prompt-book/cli.md`'s prose) for approve and reject, and add the section on dropping the wait; verify the walkthrough's docs-check tests run every command as written, including dropping the wait and a second perform kept by troupe
- [ ] 6.2 Update `docs/the-company/gates-and-decisions.md`, `docs/stagecraft/route-decisions.md`, `docs/stagecraft/read-the-lineage.md` and `docs/the-company/performances-and-runs.md` for what's built, with `prerelease` flags that match; add approver to the glossary; verify the docs check passes (glossary rows, theatre wording, links)
- [ ] 6.3 Regenerate the events reference (`uv run scripts/docs_reference.py`) and verify `test_user_docs_reference.py` passes

## 7. Integration

- [ ] 7.1 Run `uv run scripts/check.py` with its output kept in a scratch file, and verify every gate passes, including `protocol_guard` and the size gate
- [ ] 7.2 Run the first-run walkthrough end to end by hand with the scripted audition in a new repository: perform (exit 4), approve, drop the wait, perform again (kept by troupe, exit 0); record the transcript in the PR

## Workflow follow-up

- Open a draft PR closing #62, act on Claude's review, mark it ready once the review of the last push is clean, and archive before merging.
- After the troupe PR merges, open troupe-run/infrastructure's PR recording the new `gates` spec's Purpose in `oob/troupe-spec-purposes.json`.
- Ask the orchestrator whether the 0.4.0 milestone's description ("every gate is manual") changes, since milestones are managed in infrastructure.
