# Design

## Context

Config is events first (#60). A `Config.Changed` holds entries addressed by path, and `merge.py` works config out
from the stream's whole history. Each path an entry names is a point. A point's concurrent latest writes are contested
line by line: a line whose net change ends where it began drops out, and lines left that differ conflict whole. The
sweep (#119, `sweep.py`) reads hand edits to the files under `.troupe/` back into config, file by file. A file this
clone had at its last sync (`local/config/present.json`) and that's gone is a removal. A file config doesn't hold is
an addition. `syncing.py` records the sweep's edits, then the command's own change, in one batch, and writes the files
(a person's surgically, `writeback.py`).

The owner's decisions on #138 (2026-11-23) fix the behaviour. The specs carry it: config, config-hand-edits,
config-files and cli in this change. This design says how.

## Goals / Non-Goals

**Goals:**
- A rename entry that leaves every recorded event as it is.
- A merge that follows renames, and is exactly today's merge when there's none.
- Hand moves paired by value in the sweep, refusing ambiguity.
- Moved files keep their bytes.

**Non-Goals:**
- Renaming anything but a whole actor or runtime (no value paths, no kinds).
- Similarity-based detection (moved and edited stays a removal and an addition).
- An `id:` field in files (dropped, owner 2026-11-23).
- Following renames in the run's own events: they keep the name they ran under.

## Decisions

### D1. The rename entry

`{"path": [kind, new], "renamedFrom": [kind, old], "before": "sha256:<hash of the whole old group>"}`, with no
`after`. `config-changed.schema.json`'s entry gains `renamedFrom` (two keys, a kind and a name). A rename entry has no
`after`, and the entry schema gets a `oneOf` saying so. The existing `anyOf` already accepts `before` alone.

In `changes.py`:
- `Rename(source)` is an operation value, like `UNSET`.
- `change()` turns it into the entry and, for a runtime, adds an ordinary entry setting `runtime` on each actor
  (sorted by name) that names the old runtime in the config it applies to.
- `apply()` moves the group: the old one removed, and the same values put under the new name.

Keeping the actors' entries inside `change()` puts the rule in one place, for `config mv` and the sweep alike.

An event holding a rename holds no other entry under the old or the new name. `config mv`'s change never does, the
sweep's move edit never does, and `apply` relies on it. A runtime's rename touches only actor paths besides.

Rejected: recording a rename as a removal plus the new values, with a marker beside them. That duplicates the values
in the event, and the merge would have to tell a marker's values from a person's.

### D2. Entities in the merge

The merge gives each write the **entity** it names, then contests and replays in entity space. Names come back only at
the end.

- **Key.** An entity's key is `(kind, name it was born with, freed)`. `freed` is the set of rename events in the
  writing event's history that renamed something away from that name. With no renames, `freed` is always empty, so a
  name has one key on every line. Two lines that make the same new actor agree or conflict value by value, as today.
- **View.** Each event's view maps the names it sees to keys, as its history leaves them. With one parent, it's the
  parent's view after the parent's own entries. At a join (a settle, or the `extra` change a resolution check adds),
  it's worked out by D3's name contest over the join's whole history.
- **An event's entries are read against its view:**
  - a write under a name the view maps belongs to that key;
  - a write under a name it doesn't map is a **birth** of the key `(kind, name, freed)`;
  - a rename moves the old name's key to the new name;
  - a removal of the group `(kind, name)` is the key's **removal**.
- **Paths.** Each write's path becomes `(kind, <key>, rest…)`. A write of length one (`["actors"]`) stays as it is.
  Replay ignores rename entries: in entity space, a rename changes no value.
- Points, latest writes, lines and conflicts are then computed exactly as today, on entity paths. Config is replayed
  in entity space, then each key is written under its display name (D3).

**Why this is today's merge when there are no renames:** keys are then one per name, so the entity paths are the
names, and replay is unchanged. A property test checks it: for generated histories (forks, settles, removals,
re-creations, no renames), the new merge's config and conflicts equal the merge as it was. The merge as it was stays
in the test tree as an oracle (`packages/troupe/tests/merge_oracle.py`), a copy of today's `merge.py`.

Rejected:
- **Rewriting each write's path to the final name and keeping renames as no-ops.** It's simpler, but it can't tell a
  new `tester` made after the rename from the old one renamed, and it can't see a rename against a removal.
- **A stable id minted per actor (#60's alternative).** It changes every event and every file, which the owner ruled
  out.

### D3. A key's name: the name contest

Each key has one more point, its name. Its writes:
- births: from absent, to the name;
- renames: from the old name, to the new;
- removals: from the name, to removed.

They're contested by today's rule (`_round`/`_contest`, generalized over what a write's effect is): latest writes, a
line's net change, a line that ends where it began drops out, and differing lines conflict.

- **A name conflict is reported only when a rename is among its conflicting latest writes**, so a history without
  renames reports nothing new. (Births and removals alone are already contested as values, as today.) That gives:
  - two different renames;
  - a rename and a removal.

  The same rename on two lines agrees. A rename and a rename back drops out.
- **On a name conflict, both sides are left out of the name**, so the name history from before the lines decides it,
  as #190 does for values. A removal on the losing side is left out of replay too, so the entity stays with its
  values under its earlier name.
- **The display name** of a key is its contested name. A key whose contest ends in "removed" but still holds values
  (removed on one line, written on another, which is a value conflict as today) shows under the last name it had.
- **A clash** is two keys, both holding values after replay, with the same display name. That's a rename onto a name
  another line made. The renames that brought each to the name are left out, and each key falls back to its name
  before them. It's reported as a conflict on `(kind, name)`, naming the renames and, for a key with no rename, the
  changes since the split that wrote under it (as `_invalid` names changes). If a fallback name clashes again, the
  key's values are left out of config while the conflict stands. They're in its changes, and config is blocked until
  it's resolved anyway.
- A conflict's paths use display names (`actors.tester`), so `config get` shows it, and one `config mv`, `config
  unset` or `config set` resolves it, checked as today with `merge(…, extra=…)`. The extra change's view is the join
  of every head, so its names are the ones `config get` shows.

### D4. Following a name for runs

`Merged` gains `names: Names`, which answers `current(kind, name, heads)`: the key `name` has in the view at `heads`
(a run's recorded config version), and that key's display name now. It returns None when the key no longer holds
values, or `heads` aren't in the stream.

- The run summary (`client/run.schema.json`) gains `actorNow`, present only when it differs from `actor`. The runs
  projection fills it when status or logs ask, from one merge per query.
- The CLI renders `tester (now qa)`.
- `perform`'s refusal, `config.unknown-actor`, asks `names.current(actors, name, heads now)`. That's None
  for a name that was renamed away, so it asks the history instead: the latest rename away from the name on the line
  config is read from. The fix then says `tester was renamed qa: troupe perform qa`.

### D5. `troupe config mv`

- **CLI:** `troupe config mv <old> <new> [--reason] [--rehearse]`, both paths in the config path syntax. It sends
  `config-set` with one operation, `{"path": [kind, new], "renamedFrom": [kind, old]}`. A third operation shape keeps
  one method for every config change, and `config unset` already shares it. The result is `ConfigSetResult`, and the
  CLI words it as a rename.
- **Checks, in core** (`commands.py`), before anything is recorded:
  - `config.move-not-entity`: a path that isn't two keys, a kind that isn't `actors` or `runtimes`, or two kinds;
  - `config.move-built-in`: a runtime name in `defaults.RUNTIMES`, as the source or the target;
  - `config.move-source-missing`: nothing at the source in config after the sweep;
  - `config.move-target-exists`: something at the target.
  The target's name is then checked by `kinds.check` on the config the change makes, like any name.
- **Already moved by hand** (decision 3): the source entity's files are all absent from disk, and the target's are
  present (an actor's `.yaml`, or the runtime's file). Then `syncing.py` works the own change out first, on the merged
  config, and sweeps against the config it leaves. Against the renamed config, the target's files are the renamed
  entity's: equal values read as in line, and different values as an edit. The source's files are absent and not
  held, so they're nothing. The batch records the settle, the person's rename, then the sweep's edits. The sweep's
  edits would otherwise address a name that doesn't exist yet. Without a hand move, the order is today's (the sweep
  first), so a person's edit to the source's files is recorded before it's renamed.

  The own-first rule applies only to a rename operation whose files are already moved. Every other command keeps
  D1's order from #119.

### D6. Hand moves in the sweep

After classification (#119 D3), and before working edits out:

1. **Gone entities:** each group whose files are all removals: an actor's `.yaml`, and its `.md` if config holds a
   character; a runtime's file. **New entities:** each group config doesn't hold whose files were read (an actor's
   `.yaml`, plus its `.md` if present).
2. Each entity's values are worked out whole: config's group for a gone one, and the files' values (fields, plus
   character from the `.md`) for a new one. They're compared by `value_hash` of the whole group, so comments, key
   order, quoting and `$schema` never count.
3. **Pairing, per kind:** a gone entity and a new one pair when their hashes are equal. If a hash has more than one
   gone or more than one new entity, the sweep is refused with `config.move-ambiguous`, naming every file of those
   entities, before anything is worked out. A pair where either name is a built-in runtime's isn't a rename. It stays
   a removal and an addition, with a `config.move-not-detected` notice saying why.
4. **Each pair becomes one Edit:**
   - its operations: `Rename`, with the runtime's actors carried by `change()` (D1);
   - its files: the new files `{path, hash}` and the old ones `{path}`;
   - its lineage `vcs.source`: the new `.yaml` (or runtime file), with `before` the hash of the old file as config
     rendered it, and `after` the hash read.

   Its notice is `config.hand-move-recorded` (old name, new name, change id), in place of `config.hand-edit-recorded`.
5. **Unpaired:** gone and new entities of the same kind that are left unpaired go on as a removal and an addition, as
   today. While at least one of each is left, one `config.move-not-detected` notice names them and says `troupe
   config mv` keeps the history.
6. **A `.yaml` gone with its `.md` still there** is still refused as #119 says. When the sweep also found a new actor,
   the fix adds "move the .md file with it, or use troupe config mv".

A runtime's hand move edits its actors in config. Their files read as in line (they say the old name, which config
held before the sweep), so write-back splices their `runtime` line (#119 D6). If the person also edited an actor's
file to the new name, that file's edit is worked out first (edits go in path order, and `actors/` sorts before
`runtimes/`). `change()` then finds no actor naming the old runtime, and adds no duplicate entry.

The pairing goes in `sweep.py` as one function between classification and `_operations`. #45 changes the sweep too.
Its scope gives this change the move and the move back, so the pairing is ours, and whichever merges second rebases.

### D7. Moved files keep their bytes

`writeback.targets(config, seen, read, moved)` takes the renames that apply (old path to new path, for each of the
entity's files). The new path's base is the old path's bytes as the sweep saw them, written back surgically with the
values config holds. For a plain rename that's the bytes unchanged (`write_back` returns `data` when the values
match). The old paths aren't rendered, so the plan removes them. They're troupe's or read (vouched), so the plan
allows it. A moved file troupe never saw on disk (rendered only) is rendered whole, as today.

### D8. Codes

- Errors: `config.move-not-entity`, `config.move-built-in`, `config.move-source-missing`, `config.move-target-exists`,
  `config.move-ambiguous`. Each lands with code that raises it and a test (protocol_guard).
- Notices: `config.hand-move-recorded`, `config.move-not-detected`, catalogued in `notice.schema.json`.
- The protocol CHANGELOG records the additions as non-breaking.

## Risks / Trade-offs

- **The merge gets more complex.** It's the core of config, and its rules are subtle (#190).
  - The no-rename oracle property test pins today's behaviour.
  - A second property test generates histories with renames, removals, re-creations and forks. It checks every
    order of arrival gives the same config and conflicts, and every rename followed by its reverse leaves config
    as if neither happened.
  - Example tests cover each spec scenario.
- **Views at joins cost a contest per join.** Config histories are small (hundreds of events), and a chain reuses its
  parent's view. If it ever matters, views can be cached per settle.
- **A fallback name that clashes again** leaves an entity out of config while the conflict stands. Its values are in
  the events and the conflict's changes, so nothing is lost, and config is blocked until it's resolved.
- **Similarity isn't detected.** A move and an edit together lose the link, but the notice says how to keep it.
- **The PR is large.** Commits go by slice, and the review is split the same way:
  1. entries and merge;
  2. sweep pairing;
  3. command, CLI and protocol;
  4. runs and docs.

## Migration Plan

Pre-1.0, additive only. No event changes shape, and no file format changes. Rollback is reverting the PR. A history
with rename entries would then fail schema validation, so nobody records one before the change has merged.
