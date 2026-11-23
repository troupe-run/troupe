# Tasks

The orchestrator sequences full checks (`uv run scripts/check.py`): ask before each one, and check `uptime` first.
Each group lands its own tests and docs. Write each new test so it fails on main (or before its group's code), and
say so in the tick. Commit by group.

## 1. The store's drop (design D4)

- [x] 1.1 Add `remove_file` to `platform/files.py` (no error when the file is already gone; a read-only file made
      writable first, as `remove_tree` does). Verify with a test that removes a read-only file and a missing one.
- [x] 1.2 Add `droppable(events)` and `drop(events, check)` to the `EventRecorder` port (`core/events/port.py`) and
      implement them in `troupe-store-text`. The reasons are `committed` and `shares-segment`. Also
      refuse when a visible event outside `events` names one as a parent, and run `check` under the write lock before
      anything is removed. Add `events.not-droppable` to `core/errors.py` and the error schema. Verify with tests for
      each scenario of event-store's "A drop removes only whole uncommitted segments of this branch", in a real git
      theatre (committed means in HEAD or the index), and that reads after a drop give the rebuilt order and its
      notice.
- [x] 1.4 A batch can require events (design D4): `insert(..., requires=...)` through the port, the text store,
      `EventStore.record_with_lineage(s)` and `Command.record`, refusing with `events.required-missing` (in errors
      and the error schema) under the write lock; perform's run start requires its config version. Verify with
      event-store's "A batch can require events that must still be here" (`test_drop.py`) and config-hand-edits' "A
      drop that lands before a run's start" (`test_config_drop.py`, a drop injected between perform's sync and its
      start).
      Done (review on #504): each test fails with the `requires` taken out (perform's) and passes with it.
- [x] 1.3 Change the store's docs and the module docstrings that say events are never dropped, so they say a person's
      drop is the only way an event leaves. Verify by grepping `never dropped` / `never classified or dropped` in
      `packages/` and `docs/`, and leaving none that's wrong.

Done (group 1): `test_drop.py` (8 tests) and two `remove_file` tests, all new API, so they fail on main.

## 2. Finding a round trip and whether it can be dropped (design D1, D2, D3, D7)

- [x] 2.1 `core/config/abandoned.py`: `round_trip(history, closing)`. Find the linear tail since the last settle,
      replay it, take each closing edit's file scope (D1), pick the latest `X`, and merge one sweep's round trips.
      Verify with unit tests over recorded streams: restore, a comment added, several steps, a partial undo (none),
      `config set` then restore, the latest of two round trips, an actor deleted and restored (one round trip, both
      files), and a round trip that would cross a settle (none).
- [x] 2.2 `blocked(store, trip, runs_now=False)` (and `referred`, steps 2 and 3): D3's five reasons in order, with the blocker (change id, run id or
      segment). Steps 4 and 5 go through the store's `droppable`. Runs are found from `Run.Started`'s `config` heads.
      Verify with a test per reason, each built through real commands in a git theatre (sync, perform with the
      scripted runner, config set, commit).
- [x] 2.3 The keep record `.troupe/local/config/kept.json` (D7): read (absent means none; unreadable means none, plus
      `config.kept-unreadable`), add, and prune entries whose change is gone. Verify with tests for absent,
      unreadable (the notice names the file), add twice (one entry), and pruning.

Done (group 2): `test_config_abandoned.py` (20 tests over streams made by real commands); a new module, so they fail on
main. The "other-branch" reason was dropped while building: an uncommitted segment of another branch is never read here
(design D3 updated).

## 3. Reporting (design D5)

- [x] 3.1 Catalogue `config.edit-abandoned` and `config.kept-unreadable` in `protocol/notice.schema.json` (and the
      package copy), with closed details. Verify that the schema test validates a notice of each, droppable and kept.
- [x] 3.2 In `syncing.py`, after the sweep's edits are recorded (`_record_and_write` and `_record_only`), run
      `round_trip` with the sweep's change id. Unless it's kept, add the notice. `Request` gains `runs_now`, which
      `sync_files` (perform's sync) sets. Verify with config-hand-edits' scenarios for "An edit undone by hand is
      reported as abandoned" and "An abandoned edit that can't be dropped says why", through the client protocol.
- [x] 3.3 `troupe sync` repeats it: when the stream's head is a sweep's last event, run `round_trip` on that sweep, and
      report it if droppable and not kept. Verify with "Sync asks again while a drop is possible": the repeat, `config
      get` staying quiet, no notice once committed, and the unreadable keep record.

Done (group 3): `test_config_abandoned_notices.py` (18 tests, each notice validated against the schema); main
reports no `config.edit-abandoned`, so they fail there.

## 4. Drop and keep commands (design D6, D8)

- [x] 4.1 Protocol: `client/config-drop-{request,result}.schema.json` and `client/config-keep-{request,result}.schema.json`
      (closed), their messages in `core/client/messages.py`, and the codes `config.no-round-trip` and
      `config.round-trip-kept` in errors and the error schema. Verify with client-protocol's scenarios (a request
      naming `segments` is refused; results and errors validate).
- [x] 4.2 `config-drop` and `config-keep` in `core/config/commands.py`, holding the config files' lock. Drop re-checks
      under the store's lock through `check`, supports `rehearse`, and removes a keep entry. Verify with config-hand-edits'
      "A person drops or keeps an abandoned edit" scenarios. After a drop, config and the file are as before the edit,
      and the next sync records nothing and writes nothing.
- [x] 4.3 CLI: `troupe config drop <change> [--rehearse]` and `troupe config keep <change> [--rehearse]` in
      `cli/config.py` and the parser, rendered as D8 says, with exit codes from `exit_codes.py`. Verify with cli
      tests for the two new scenarios of "Config and sync commands", a rehearsal's "would change" exit code, and a
      refusal's exit code. Also check the lazy-import test ("A command loads only its own handlers") still passes.

Done (group 4): `test_config_drop.py` (9) and `test_cli_config_abandoned.py` (4, including 6.1's end-to-end test); the
methods and subcommands don't exist on main.

## 5. Docs and the protocol record (design D9)

- [x] 5.1 `docs/stagecraft/hand-edit-config.md`, "Undoing an edit"; `docs/prompt-book/cli.md`, the two commands;
      `contributing/config.md`, `abandoned.py` and the store's drop. Verify with the docs checks in `scripts/check.py`
      (links and the defaults table), and by reading each page against the specs.
- [x] 5.2 The protocol changes (two commands, two notices, four error codes) reach the protocol CHANGELOG and
      version through release-please, from `feat(protocol)` and `feat(config)` commits: nobody edits either by hand
      (`contributing/releasing.md`). Verify the commits' types and scopes before the PR, and that no CHANGELOG or
      `version.json` is in the diff.
      Done: a `feat(config)` commit (c2b91085) and the review's `fix(config)` (c3fbbd92); `git diff --stat main..HEAD` holds no CHANGELOG or version file.

## 6. Integration

- [x] 6.1 An end-to-end test through the CLI in a real git theatre: edit, sync, restore, sync (notice), `config drop`,
      `git status` shows no event files from either sync, and a final sync records nothing. Verify by running it.
- [x] 6.2 Full `uv run scripts/check.py` (slot from the orchestrator, `uptime` under ~40), and no stray processes
      (`pgrep -fl "python.*(fake_claude.py|while True: pass)"`). Verify by keeping the full log in the scratchpad and
      reading every FAILED line.
      Done: the commit's check (slot from the orchestrator, load ~9): first run 7550 passed, 1 failed
      (`test_config_alone_needs_one_of_its_commands`, whose usage text now lists drop and keep; updated); second run
      all gates passed in 296 s. No stray processes.

## Workflow follow-up

- Draft PR closing #45. Act on Claude's review, mark it ready, archive, and hand it to the owner to queue.
- After the merge: check #45 is closed and its card says Done.
