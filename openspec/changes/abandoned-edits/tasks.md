# Tasks

The orchestrator sequences full checks (`uv run scripts/check.py`): ask before each one, and check `uptime` first.
Each group lands its own tests and docs. Write each new test so it fails on main (or before its group's code), and
say so in the tick. Commit by group.

## 1. The store's drop (design D4)

- [ ] 1.1 Add `remove_file` to `platform/files.py` (no error when the file is already gone; a read-only file made
      writable first, as `remove_tree` does). Verify with a test that removes a read-only file and a missing one.
- [ ] 1.2 Add `droppable(events)` and `drop(events, check)` to the `EventRecorder` port (`core/events/port.py`) and
      implement them in `troupe-store-text`. The reasons are `committed`, `other-branch` and `shares-segment`. Also
      refuse when a visible event outside `events` names one as a parent, and run `check` under the write lock before
      anything is removed. Add `events.not-droppable` to `core/errors.py` and the error schema. Verify with tests for
      each scenario of event-store's "A drop removes only whole uncommitted segments of this branch", in a real git
      theatre (committed means in HEAD or the index), and that reads after a drop give the rebuilt order and its
      notice.
- [ ] 1.3 Change the store's docs and the module docstrings that say events are never dropped, so they say a person's
      drop is the only way an event leaves. Verify by grepping `never dropped` / `never classified or dropped` in
      `packages/` and `docs/`, and leaving none that's wrong.

## 2. Finding a round trip and whether it can be dropped (design D1, D2, D3, D7)

- [ ] 2.1 `core/config/abandoned.py`: `round_trip(history, closing)`. Find the linear tail since the last settle,
      replay it, take each closing edit's file scope (D1), pick the latest `X`, and merge one sweep's round trips.
      Verify with unit tests over recorded streams: restore, a comment added, several steps, a partial undo (none),
      `config set` then restore, the latest of two round trips, an actor deleted and restored (one round trip, both
      files), and a round trip that would cross a settle (none).
- [ ] 2.2 `dropping(store, trip, runs_now=False)`: D3's six reasons in order, with the blocker (change id, run id or
      segment). Steps 4 to 6 go through the store's `droppable`. Runs are found from `Run.Started`'s `config` heads.
      Verify with a test per reason, each built through real commands in a git theatre (sync, perform with the
      scripted runner, config set, commit).
- [ ] 2.3 The keep record `.troupe/local/config/kept.json` (D7): read (absent means none; unreadable means none, plus
      `config.kept-unreadable`), add, and prune entries whose change is gone. Verify with tests for absent,
      unreadable (the notice names the file), add twice (one entry), and pruning.

## 3. Reporting (design D5)

- [ ] 3.1 Catalogue `config.edit-abandoned` and `config.kept-unreadable` in `protocol/notice.schema.json` (and the
      package copy), with closed details. Verify that the schema test validates a notice of each, droppable and kept.
- [ ] 3.2 In `syncing.py`, after the sweep's edits are recorded (`_record_and_write` and `_record_only`), run
      `round_trip` with the sweep's change id. Unless it's kept, add the notice. `Request` gains `runs_now`, which
      `sync_files` (perform's sync) sets. Verify with config-hand-edits' scenarios for "An edit undone by hand is
      reported as abandoned" and "An abandoned edit that can't be dropped says why", through the client protocol.
- [ ] 3.3 `troupe sync` repeats it: when the stream's head is a sweep's last event, run `round_trip` on that sweep, and
      report it if droppable and not kept. Verify with "Sync asks again while a drop is possible": the repeat, `config
      get` staying quiet, no notice once committed, and the unreadable keep record.

## 4. Drop and keep commands (design D6, D8)

- [ ] 4.1 Protocol: `client/config-drop-{request,result}.schema.json` and `client/config-keep-{request,result}.schema.json`
      (closed), their messages in `core/client/messages.py`, and the codes `config.no-round-trip` and
      `config.round-trip-kept` in errors and the error schema. Verify with client-protocol's scenarios (a request
      naming `segments` is refused; results and errors validate).
- [ ] 4.2 `config-drop` and `config-keep` in `core/config/commands.py`, holding the config files' lock. Drop re-checks
      under the store's lock through `check`, supports `rehearse`, and removes a keep entry. Verify with config-hand-edits'
      "A person drops or keeps an abandoned edit" scenarios. After a drop, config and the file are as before the edit,
      and the next sync records nothing and writes nothing.
- [ ] 4.3 CLI: `troupe config drop <change> [--rehearse]` and `troupe config keep <change> [--rehearse]` in
      `cli/config.py` and the parser, rendered as D8 says, with exit codes from `exit_codes.py`. Verify with cli
      tests for the two new scenarios of "Config and sync commands", a rehearsal's "would change" exit code, and a
      refusal's exit code. Also check the lazy-import test ("A command loads only its own handlers") still passes.

## 5. Docs and the protocol record (design D9)

- [ ] 5.1 `docs/stagecraft/hand-edit-config.md`, "Undoing an edit"; `docs/prompt-book/cli.md`, the two commands;
      `contributing/config.md`, `abandoned.py` and the store's drop. Verify with the docs checks in `scripts/check.py`
      (links and the defaults table), and by reading each page against the specs.
- [ ] 5.2 The protocol CHANGELOG: two commands, two notices, three error codes. Bump the protocol version as
      `contributing/` says for an additive change. Verify with the protocol version test.

## 6. Integration

- [ ] 6.1 An end-to-end test through the CLI in a real git theatre: edit, sync, restore, sync (notice), `config drop`,
      `git status` shows no event files from either sync, and a final sync records nothing. Verify by running it.
- [ ] 6.2 Full `uv run scripts/check.py` (slot from the orchestrator, `uptime` under ~40), and no stray processes
      (`pgrep -fl "python.*(fake_claude.py|while True: pass)"`). Verify by keeping the full log in the scratchpad and
      reading every FAILED line.

## Workflow follow-up

- Draft PR closing #45. Act on Claude's review, mark it ready, archive, and hand it to the owner to queue.
- After the merge: check #45 is closed and its card says Done.
