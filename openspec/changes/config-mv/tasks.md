# Tasks

## 1. The rename entry (design D1)

- [x] 1.1 Add `renamedFrom` to the entry in `protocol/schemas/events/config-changed.schema.json` (and its bundled copy), with a rename entry carrying no `after`. Update `Config.Changed`'s description. Verify with `test_config_schemas.py`: a valid rename entry passes, one with an `after` is refused, and the generated model agrees with the schema on generated entries with `renamedFrom`.
- [x] 1.2 Add `Rename` to `core/config/changes.py`: `change()` makes the entry, plus a runtime's actors' `runtime` entries, and `apply()` moves the group. Verify with new `test_config_changes.py` cases: an actor's rename, a runtime's rename carrying two actors, and apply moving every value.

## 2. Entities in the merge (design D2, D3, D9)

- [x] 2.0 Fix #503: contest a point again when another point's contest leaves out one of its covering writes (design D9). Verify with a plain test of the six-event reproduction, failing before and passing after, and with the merge property test generating removals and re-creations.
- [x] 2.1 Copy `merge.py` as fixed by 2.0 into `packages/troupe/tests/merge_oracle.py` as the oracle, and add a property test that generates histories with no renames and checks the new merge's config and conflicts equal the oracle's. Verify it passes before 2.2 starts.
- [x] 2.2 Give each write its entity in `merge.py`: views (with one parent: carried; at a join: contested), keys, births, renames and removals, entity paths, replay in entity space, and display names. Verify with the oracle property test still passing, and with examples for "A character set on a branch that didn't rename", "A rename and a rename back", and "A new tester after the rename" / "A concurrent change still follows".
- [x] 2.3 Add the name contest's conflicts: two renames, a rename and a removal, and a clash, each left out of replay as D3 says and named on its display path. Verify with examples for each "Renames that can't both hold" scenario, including resolving with `config mv` through `merge(…, extra=…)`.
- [x] 2.4 Add a property test for histories with renames (forks, settles, removals, re-creations). Check that every order of arrival gives the same config and conflicts, and that a rename followed by its reverse leaves config as if neither happened. Verify it passes at the `ci` hypothesis profile.
- [x] 2.5 Add `Merged.names.current(kind, name, heads)`. Verify with tests for a chain of renames, a removed actor (None) and heads not in the stream (None).

## 3. `troupe config mv` (design D5)

- [x] 3.1 Add the rename operation to `client/config-set-request.schema.json` and `core/client/messages.py`. Verify with `test_client_messages.py`: it round-trips, and one with a value or an unset is refused.
- [x] 3.2 Add the checks to `core/config/commands.py`: `config.move-not-entity`, `config.move-built-in`, `config.move-source-missing` and `config.move-target-exists`, each with its exit code in `core/errors.py` and its entry in `error.schema.json`. Verify with `test_config_mv.py` cases for each refusal (nothing recorded), and with protocol_guard.
- [x] 3.3 In `syncing.py`, work the own change out first and sweep after it when the rename's files are already moved, recording the settle, then the person's rename, then the sweep's edits. Verify with `test_config_mv.py` cases: "Config mv on files already moved", "Moved and edited, then config mv", and a plain mv still sweeping first.
- [x] 3.4 Move files keeping their bytes in `writeback.targets` (design D7). Verify with `test_config_mv.py` cases: "A hand-formatted actor renamed" (byte-identical) and "A runtime renamed under its actors" (only the `runtime` line changes).
- [x] 3.5 Add `troupe config mv <old> <new> [--reason] [--rehearse]` to the CLI parser and renderer. Verify with `test_cli_config.py` cases: the output names both names, the change and the files; one path is a usage error; `--rehearse` records nothing.
- [x] 3.6 Document `troupe config mv` in `docs/prompt-book/cli.md` (its entry, and the Commands list) and in `docs/stagecraft/hand-edit-config.md`. Verify with `test_cli_docs.py` and the user-docs tests.

## 4. Hand moves in the sweep (design D6)

- [x] 4.1 Pair gone and new entities by value hash in `sweep.py`, making one move Edit per pair, with the files, lineage source and `config.hand-move-recorded` notice. Verify with `test_config_hand_moves.py` cases: "An actor moved by hand", "Formatting doesn't count", "A runtime moved by hand carries its actors", "Moved and moved back before a sweep", and "Moved back after a sweep".
- [x] 4.2 Refuse ambiguous pairings with `config.move-ambiguous` (exit code, error schema). Verify with `test_config_hand_moves.py` cases "Two identical actors moved" and "One actor copied to two names", nothing recorded.
- [x] 4.3 Add `config.move-not-detected` for unpaired gone and new entities of a kind, and for a built-in runtime's file moved, and catalogue both new notices in `notice.schema.json`. Verify with `test_config_hand_moves.py` cases "Moved and edited at once" and "A built-in runtime's file moved".
- [x] 4.4 Extend the "an actor needs its .yaml" fix when a new actor arrived in the same sweep. Verify with `test_config_hand_moves.py` cases for the modified "A character left without its actor" scenario.
- [x] 4.5 Add an end-to-end hand-move test to `test_hand_edit_end_to_end.py`: `git mv` both files, `troupe sync`, then `troupe config get` shows `qa`, and a second sync records nothing. Verify it passes.

## 5. Runs follow a rename (design D4)

- [x] 5.1 Add `actorNow` to the run summary schema and the runs projection, filled from `Merged.names`. Verify with `test_runs_follow_renames.py` cases (status `--json` validated against the result schema): renamed, chain, not renamed, removed.
- [x] 5.2 Render `tester (now qa)` in `troupe status` (list and one run) and `troupe logs`. Logs adds its `actor:` line only when the actor was renamed, so existing logs output is unchanged. Verify with `test_runs_follow_renames.py` cases for each "Status and logs show an actor's current name" scenario, and `test_cli_runs.py` still passing.
- [x] 5.3 Name the new name in `perform`'s `config.unknown-actor` fix. Verify with `test_runs_follow_renames.py` cases "Performing the old name" and a chain of renames.
- [x] 5.4 Document both in `docs/prompt-book/cli.md`'s `status` and `logs` entries. Verify with the user-docs tests.

## 6. Protocol and contributor docs

- [x] 6.1 Describe the rename entry, entities, keys, the name contest, #503's re-contest, hand-move pairing and the new codes in `contributing/config.md`. The protocol CHANGELOG is written by release-please from the commits (`feat(protocol)`, `feat(config)`, `feat(cli)`, `fix(config)`), so it isn't edited by hand. Verify with `test_user_docs_*.py` and a read-through against design D2, D3, D6 and D9.

## 7. Integration

- [x] 7.1 Run `uv run scripts/check.py` (full) once its slot is agreed with the orchestrator, and record the result. Verify it reports every check passed.
- [x] 7.2 Run `openspec validate config-mv --strict`. Verify it reports the change valid.

## Workflow follow-up

- Open a draft PR closing #138, act on Claude's review of the last push, then mark it ready.
- Archive the change on the branch before the merge.
- After the merge, check #138 is closed and its card is Done, and comment with the PR and the archived change.
