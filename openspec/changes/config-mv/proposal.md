# Proposal

## Why

There's no way to rename an actor or a runtime and keep its history. Moving `actors/tester.yaml` to `actors/qa.yaml`
by hand reads as removing `tester` and adding `qa`, and so does unsetting one and setting the other. Then the runs
recorded under `tester`, and any change another branch makes to `tester`, lose track of it. #138 records the owner's
decisions (2026-11-23) on how a rename should work. #119's sweep (troupe#490) is what lets troupe see a hand move
at all.

## What Changes

- **`troupe config mv <kind>.<old> <kind>.<new>`** renames an actor or a runtime as one change. It records one
  `Config.Changed` with a new kind of entry, `{"path": [kind, new], "renamedFrom": [kind, old], "before": <group
  hash>}`, and the sync moves the files, keeping their bytes. No recorded event changes shape.
- **A runtime's rename carries its actors with it.** The same change sets `runtime` to the new name on every actor
  that names the old one.
- **What `config mv` refuses**, recording nothing:
  - anything but a whole actor or runtime, and a rename across kinds;
  - a source that doesn't exist;
  - a target that already exists (there's no `--force`);
  - a built-in runtime's name, as the source or as the target.
- **A hand move is a rename.** When a sweep sees an entity's files go (files this clone had at its last sync) and
  another entity's files arrive with equal values, it records the rename by the unknown author, not a removal and an
  addition. Values are compared as values, so comments, key order, quoting and `$schema` don't count.
  - Moved and edited at once: a removal and an addition, as today, and a notice says that `config mv` keeps the
    history.
  - Ambiguous (equal values on more than one side): refused, `config.move-ambiguous`.
  - `config mv` on files already moved by hand records the rename, by the person, and writes nothing. That's also
    the way out of an ambiguous move.
- **Changes on other branches follow a rename.** The merge works out which entity each write names through renames
  on every line. A change on another branch to `actors.tester.character` lands on `qa`. These are conflicts:
  - two lines renaming one entity differently;
  - a rename and a removal of the same entity;
  - a rename onto a name another line created.

  A history with no renames merges exactly as today.
- **Runs follow a rename.** A run keeps the actor name it ran under. `troupe status` and `troupe logs` show
  `tester (now qa)` when the actor has been renamed since, following a chain of renames. `troupe perform tester`
  after the rename is refused as today, and its fix names `qa`.
- Protocol (additive, `feat`):
  - the change entry's `renamedFrom`;
  - the `config-set` request's rename operation, which `config mv` sends;
  - a run summary's `actorNow`;
  - new error codes (`config.move-*`) and notices (`config.hand-move-recorded`, `config.move-not-detected`).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `config`: a rename entry; `config mv` and what it refuses; a merge that follows renames, with its three conflicts.
- `config-hand-edits`: a hand move recorded as a rename; moved and edited; ambiguous moves; `config mv` on files
  already moved.
- `config-files`: a rename moves an entity's files keeping their bytes, and writes back a runtime's actors
  surgically.
- `cli`: the `troupe config mv` command; status and logs show an actor's current name; perform's fix names a rename.

## Impact

- `core/config`:
  - `changes.py`: the rename entry and operation.
  - `merge.py`: the entities and the name contest.
  - `sweep.py`: pairing removals and additions.
  - `syncing.py`: own-first ordering for a mv on moved files.
  - `writeback.py`: a moved file's bytes.
  - `commands.py`: the mv checks.
- `core/runs` projections: `actorNow`.
- The `perform` refusal.
- CLI: `config mv`, and the status and logs rendering.
- `protocol/schemas`:
  - `events/config-changed`;
  - `client/config-set-request` and the run summary;
  - `error` and `notice` catalogues;
  - protocol CHANGELOG.
- Docs:
  - `docs/prompt-book/cli.md`;
  - `docs/stagecraft/hand-edit-config.md`;
  - `contributing/config.md`.
- #45 (abandoned edits) changes the sweep in parallel. Whichever merges second rebases.
