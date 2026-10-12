# Tasks

## 1. Workspace and package scaffolding

- [x] 1.1 Create `packages/troupe-stage-local` (src layout, `py.typed`, licence, README, the `troupe.stages` entry
  point registering `local`, per design D1) and add it to the dev group. Verify `uv sync` succeeds and
  `uv run python -c "import troupe_stage_local"` exits 0
- [x] 1.2 Extend `pyproject.toml` (ruff `src`, mypy `files` and `mypy_path`, pytest `testpaths`) for the new package,
  and add the import contracts from design D1: `troupe` never imports `troupe_stage_local`; `troupe.cli` imports
  nothing from `troupe.core.runs`, `troupe.core.stages` or `troupe.core.policy` (only `troupe.core.client`); and
  `troupe_stage_local` imports no surface. Verify each contract fails on a deliberate violation (record the output for
  the PR), and `uv run scripts/check.py` passes

## 2. Lineage records the stage

- [x] 2.1 Add the required, nullable `stage` to `protocol/schemas/lineage.schema.json`, with the rule
  that `allowedBy` is non-null exactly when `effects` is `unenforced` (design D7). Verify with schema tests that a
  null stage, an enforced stage with no allowance and an allowed unenforced stage are accepted, and a missing `stage`,
  an unenforced stage with a null `allowedBy`, an enforced one with an allowance and an unknown `effects` are rejected
- [x] 2.2 Add `stage` to `troupe.core.events.lineage` (`Lineage`, `to_data`, `lineage_problem`) and to `Command`
  (design D7), with `null` for every existing caller. Verify the existing lineage tests, the "types and schema agree"
  test extended to every stage shape, and a test that the service refuses an unenforced stage without an allowance
  with `events.lineage-invalid`, all pass
- [x] 2.3 Add `Command.acting_as(actor, via)` to the event-store service (design D8): records with another actor and
  via, sharing the command's change id and cause. Verify with a test that events recorded through the view and through
  the command share one change id and a command cause naming it, and that the view's events carry its actor and via
- [x] 2.4 Document `stage` in `docs/event-store.md`'s lineage table and `protocol/README.md`. Verify
  `test_event_store_doc.py` passes

## 3. Policy

- [x] 3.1 Add `troupe.core.policy` with `allow_unenforced_local_stage` (default `ALLOW_UNENFORCED_LOCAL_STAGE = False`
  in `troupe.core.defaults`), its environment source `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE`, and values that
  carry their source (design D6). Add `policy.invalid-value`. Verify tests for: unset and empty → false from
  `default`; `true` and `false` → that value from `env`; and `yes`, `TRUE`, ` true` and `1` each → `policy.invalid-value`
  naming the variable, the value and the accepted values
- [x] 3.2 Document the policy seam and its variable in a new `docs/runs.md` section, marked interim (replaced by config
  and #8). Verify the doc's variable name and default are checked against the code by a test, like
  `test_runners_doc.py`

## 4. Stages

- [x] 4.1 Add the stage port, `Admission`, and `load_stage(name)` in `troupe.core.stages`, with `stage.unknown`, and
  `STAGE = "local"` in `troupe.core.defaults` (design D5). Verify with a test that an unknown name fails with
  `stage.unknown` naming the installed stages
- [x] 4.2 Implement the local stage in `troupe_stage_local`: workspace is the theatre root; `admit` refuses with
  `stage.effects-unenforced` unless the policy allows it, and otherwise admits as `unenforced`, allowed by the setting
  and its source. Verify tests for the default refusal (with the fix naming the setting and the variable), an allowed
  admission's record, and the registration test (found by name through the entry point)
- [x] 4.3 Document the local stage and #3's rule (including why an actor that declares nothing is refused) in
  `docs/runs.md`. Verify the doc test passes

## 5. Theatre and interim names

- [x] 5.1 Add `troupe.core.theatre.find_theatre(start)`: the nearest ancestor containing `.troupe/`, else
  `theatre.not-found` naming the start directory (design D3). Verify tests for the start directory itself, a
  subdirectory, a directory with no theatre above it (nothing created), and a `.troupe` that is a file rather than a
  directory (not a theatre)
- [x] 5.2 Add `troupe.core.interim` with `RUNNERS` (`scripted` → `[sys.executable, "-m", "troupe_runner_scripted"]`)
  and `runner.unknown` (design D4). Verify a test that `scripted` resolves to a command that passes the runner
  conformance suite, and that an unknown name fails naming the known ones

## 6. Client protocol

- [x] 6.1 Write `protocol/schemas/client/` (design D2): the `perform`, `status` and `logs` requests, updates and
  results, and the shared `run-summary` definitions. List them in `protocol/README.md`. Verify schema tests with valid
  and invalid examples: an absolute path, `..` or a drive in `effectCheck.paths`; an actor name breaking its pattern;
  an `effectCheck` that is neither `none` nor `files`; an unknown field at each level; a run prefix shorter than 8
- [x] 6.2 Add the message types in `troupe.core.client` (strict `from_data`, `to_data`), `client.invalid-request` and
  `client.unknown-method` (both exit 2). Verify every message both ways against its schema, including a hypothesis
  property test that schema-generated messages parse and serialise back unchanged, and tests that each kind of
  malformed request names its field
- [x] 6.3 Add the `Session` context and the dispatcher `call(method, params, session, on_update)` (design D2). Verify
  with a test that an unknown method is refused, and that a request is parsed before any method runs (an invalid
  `perform` starts no runner and writes nothing)

## 7. Recording a run

- [x] 7.1 Add the `Run` aggregate and its events (`Run.Started`, `Run.Reported`, `Run.Ended`) in `troupe.core.runs`,
  with `run.out-of-sequence` (design D8). Verify tests for: a repeated `seq`, a gap, a report before the start or after
  the end, a second start or end, all refused with nothing recorded; and a hypothesis test that any gap-free sequence
  of run events is accepted and reads back in order
- [x] 7.2 Add `perform` in `troupe.core.runs`: resolve identity, read policy, admit on the stage, mint the run id,
  take the run's lease (`.troupe/local/runs/<id>/`), store instructions and options as artifacts, run the host with
  `on_event` recording through `asyncio.to_thread`, record `Run.Started` on `init` (or at the end without one), each
  `Run.Reported`, then `Run.Ended`, and send `started`, `event` and `notice` updates (design D8, D9). Verify with
  scripted-runner tests, recording into a real git theatre, that a successful run's stream is start, `init`, the
  other events in `seq` order, then the end with `succeeded`; its lineage (person via `cli` for the start, agent via
  `runner` for the rest, one change id, the stage's allowance); and the options artifact's bytes
- [x] 7.3 Verify the run's end for each outcome the scripted runner can produce (`succeeded`, `failed` with each error
  code, `crashed`, `timed-out`, `cancelled`, `could-not-start`), each recorded with the outcome and error the run host
  derived; and that a run that never sends `init` records its start with no runner name or version, then its end
- [ ] 7.4 Handle recording failures (design D9): a failure in `on_event` cancels the run, records no further events,
  tries `Run.Ended` with `recording.failedAt` and the error, and fails with `run.recording-failed`. Verify with a test
  that injects a store failure at `seq` 2, and one where `Run.Ended` also fails (the error says so, and `status` shows
  the run `interrupted`)
- [x] 7.5 Verify the refusals that leave nothing behind: no identity, a malformed policy value, the default policy on
  the local stage, an unknown runner, and an unknown stage each fail before a runner starts, with no event, artifact or
  lease written

## 8. Projections and queries

- [ ] 8.1 Add the runs and run-log projections as folds over recorded events (design D12), and the derived states
  (`running`, `ended`, `interrupted`, `unfinished-elsewhere`) with the lease probe (design D11) and the notices
  `run.interrupted` and `run.unfinished-elsewhere`. Verify tests for each state: a held lease, a recorded end, a lease
  left by a killed `perform` process (a real child process killed mid-run), and a run whose events arrived by a git
  merge from another clone
- [ ] 8.2 Implement the `status` query: recent runs, newest first, up to `STATUS_RUNS_LIMIT` (20, in
  `troupe.core.defaults`) or the request's `limit`, and one run's summary; run id resolution by full id or a unique
  prefix of at least 8 hex digits, with `run.not-found` and `run.ambiguous-id` (design D13). Verify tests for each,
  including two runs sharing an 8-digit prefix, and that the store's notices come back with the result
- [ ] 8.3 Implement the `logs` query, with `follow` streaming `event` updates through the store's subscription until
  the run's end, or until the run stops being `running` (design D13). Verify tests that following from a second
  process sees each event as it is recorded and stops on the end, and that following an `interrupted` run returns at
  once with its notice
- [ ] 8.4 Document runs, their states, `status`, `logs` and the run events in `docs/runs.md`, and link it from
  `docs/runners.md` and `docs/event-store.md`. Verify the doc test (states, notice and error codes, default limit)
  passes

## 9. Platform: interrupts

- [ ] 9.1 Add `troupe.platform.interrupts`: a context manager that calls back on `SIGINT`, and `SIGBREAK` on Windows,
  restoring the previous handlers on exit (design D10). Add `signal` use here to the platform contract's allowance.
  Verify a test that sends the interrupt to a real child Python process on each OS in CI (`CTRL_C_EVENT` to a new
  console process group on Windows) and observes the callback, and that the previous handler is restored
- [ ] 9.2 Document interrupts in `docs/platform.md`. Verify `test_platform_docs.py` passes

## 10. The CLI

- [ ] 10.1 Add `ExitCode.CANCELLED = 130` and document it in `docs/cli/exit-codes.md` (design D14). Verify
  `test_exit_codes_doc.py` passes
- [ ] 10.2 Add `troupe perform` in `troupe.cli.commands` (design D4, D14): find the theatre, build the request from
  `--runner`, `--runner-options` (strict JSON, `perform.options-invalid`), `--instructions` and exactly one of
  `--expect`/`--no-effect-check` (paths from the working directory, `perform.path-outside-theatre`), call the core,
  render updates on standard error, catch Ctrl-C through the platform hook (the `run.cancelling` notice, repeated on
  later presses), and exit by outcome. Verify CLI tests for each usage error, each refusal, the stdout/stderr split on
  success and on failure, and an end-to-end test that runs `troupe perform` as a real process with the scripted
  runner and policy allowed, and finds the events in the theatre
- [ ] 10.3 Verify Ctrl-C end to end on Linux, macOS and Windows in CI: a `troupe perform` process with a hanging
  scripted runner, interrupted once, exits 130 and records `cancelled`; interrupted twice with a runner that ignores
  cancel, shows the notice twice and still records the end after the grace period
- [ ] 10.4 Add `troupe status` and `troupe logs` (with `--limit`, `--follow` and `--json`). Verify CLI tests that
  `--json` output validates against the result schemas (and, with `--follow`, each line against the update schema),
  that notices go to standard error, and an end-to-end test that `troupe logs --follow` in a second process shows a
  running run's events and exits 0 when it ends
- [ ] 10.5 Register the three commands in `COMMANDS`, and document them in `docs/cli/README.md`, marking the
  `perform` flags as interim (replaced by config). Verify `test_cli_docs.py` passes and `troupe --help` lists the
  three commands

## 11. Errors, notices and the whole

- [ ] 11.1 Add every new error and notice code from design D15 to `CODES` and `troupe.core.notices`, with their exit
  codes. Verify the test that serialises every declared error and notice and validates each against its schema
- [ ] 11.2 Run `uv run scripts/check.py` and the full suite; confirm CI passes on Linux, macOS and Windows. Record the
  run in the PR

## Workflow follow-up

- Open the PR with `Closes #36` and `Closes #3`, then run `/opsx:archive` on the branch before merging.
- After the merge, comment on #36 and #3 with the PR and the archived change, and on #14 with what this change
  settled for the skeleton (no server; the client protocol in `protocol/schemas/client/`).
- #46 (the project constraint that overclaims what JSON-RPC enforces) is a separate fix and isn't in this change.
