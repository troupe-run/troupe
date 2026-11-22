# Proposal

## Why

The files under `.troupe/` are a one-way projection today: troupe writes them from config's events and never reads them
back, so a person who edits one by hand gets `config.file-not-troupes` on their next command (#60, design D8). The
first run works round it by setting the character with `troupe config set actors.lead.character=@<file>`. Config by
hand is 0.3.0's core: a person edits a file, and troupe records the edit. Tracked as troupe-run/troupe#119, whose
scope and the owner's four decisions (2026-11-21) are on the issue. It rests on #5 (net change at command boundaries,
no watching), #6 (layout and write-back rules) and #137 (`--rehearse`), and unblocks #138 (renames) and #45
(abandoned edits).

## What Changes

- **The sweep.** Before each command that uses config, troupe reads every config file's values and compares them
  with what config holds for that file. Each file whose values differ is recorded as its own `Config.Changed`: the
  net change since troupe last saw it (3 → 5 → 7 is 3 → 7; 3 → 5 → 3 is nothing). Its lineage has the explicit
  `unknown` actor, `via: file`, and `vcs.source` naming the file with its hash before and after. One sweep's changes
  share a change id of their own. Formatting, comments and key order are never a change.
- **The file wins** (owner, decision 1). A file put back with `git restore`, or restored from an earlier commit, is
  recorded as a hand edit, and the restore stands. Deleting a file removes what it held: the character, or with both
  files, the actor. Adding a file adds what it holds.
- **The mid-save guard.** A file that's present but holds no values (empty, or only its `$schema` lines) is refused,
  never read as "remove everything". A file that doesn't parse, or fails its schema or its runner's options schema,
  is refused with `config.file-invalid`, naming the file and the rule; nothing from any file is recorded. A file that
  changes while troupe reads it is read again, then refused with `config.file-changing`.
- **A hand edit resolves a config conflict** (owner, decision 4), as a `config set` of every conflicting value does.
  The sweep's edits, together with the command's own change, must set every conflicting value; a partial resolution
  is refused naming what's left, and the edited file is kept. A value matching neither side resolves the conflict
  with that value. Two conflicting values in one edited file are both resolved, since the file wins, and every
  conflict a sweep resolves is named, with the value it took, in a `config.conflict-resolved` notice (owner,
  2026-11-21).
- **Surgical write-back.** When troupe writes a file a person edited, it changes only the values that changed and
  keeps every other line byte for byte. A new key goes where the schema's order says, among the keys already there.
  A file troupe makes new is written as today. troupe's own write-back reads back as in line, so it never records
  anything: no loop. Before replacing a file, troupe checks it's still what the sweep read.
- **BREAKING: `troupe sync` replaces `troupe flush`** (owner, decision 2), with `--rehearse` and `--force` and no
  alias. The client protocol's `flush` method becomes `sync`. `--force` replaces a file the sweep refused, keeping a
  copy.
- **`troupe config get` sweeps first** (owner, decision 3), so it shows what the files say. With a partial
  resolution, it records nothing and shows the conflict with a notice.
- **Existing rules stay.** A staged write a crash cut short is finished before the sweep. A file git merged from
  versions troupe wrote follows #141's and #156's rules until a person edits it; once they've edited it (conflict
  markers gone), it's read as their edit. A file with conflict markers and a side troupe didn't write is still
  refused with `config.file-not-troupes`.
- **The first run edits the character file again** (the owner's comment on #119): `troupe init --audition`'s
  character line, its cli scenario, `docs/opening-night/first-performance.md`, `first-theatre.md`, and
  `docs/prompt-book/cli.md`. `docs/stagecraft/hand-edit-config.md` describes the sweep.

## Capabilities

### New Capabilities

- `config-hand-edits`: reading a person's edits to the config files back into config. Covers the sweep, what counts
  as a change, lineage for an unknown author, additions, removals and restores, the mid-save guard, invalid files,
  resolving conflicts by hand, and rehearsing it.

### Modified Capabilities

- `config-files`: `troupe sync` replaces `troupe flush` throughout. "Only a file troupe wrote is replaced" becomes
  "a file troupe can't read is never replaced". A file troupe writes new keeps today's form, and a file a person
  edited is written back surgically, only if it's still what the sweep read. A file git merged that a person then
  edited is read as their edit.
- `config`: config is worked out only from events, and a hand edit changes it through the change the sweep records.
  The one-change-per-command rule names the sweep's own changes. Conflicts are resolved by the changes one command
  records together, including the sweep's.
- `cli`: `troupe sync` replaces `troupe flush` (commands, rehearsal exit codes). `troupe init --audition` says to edit
  the character's file.
- `client-protocol`: the `flush` method becomes `sync`.
- `settings`: scenarios that named `flush` name `sync`.
- `lineage`: the sweep's changes share a change id of their own, apart from the command's.

## Impact

- **Code:** `packages/troupe/src/troupe/core/config/`: a new sweep module (read, compare, classify, record),
  `projection.py` (comparing by values, surgical splicing by YAML node spans, compare-and-swap before replacing),
  `commands.py` (sweep before set, unset, get, perform and sync; `flush_files` becomes `sync`), `stream.py`
  (recording several changes in one batch, conflict check across the batch), `kinds.py` (reading a file's values by
  its kind); `core/runs/perform.py`; `core/errors.py` (`config.file-invalid`, `config.file-changing`); `cli/table.py`,
  `cli/config.py`, `cli/init.py`.
- **Protocol:** `client/flush-*.schema.json` become `client/sync-*.schema.json`; the `config-changed` schema's
  description stops saying one command records exactly one; new error codes in `error.schema.json`. The protocol
  CHANGELOG records the breaking rename.
- **Docs:** `docs/stagecraft/hand-edit-config.md`, `docs/opening-night/first-performance.md`, `first-theatre.md`,
  `docs/prompt-book/cli.md`, `contributing/config.md`, and every page that names `troupe flush`.
- **Infrastructure:** the new `config-hand-edits` spec's Purpose goes into troupe-run/infrastructure's
  `oob/troupe-spec-purposes.json` through a PR merged after this one.
- **Dependencies:** none new (ruamel.yaml's composer gives the node spans the write-back needs).
- Out of scope: abandoned edits (#45), renames and detecting hand moves (#138), watching files (#5, rejected), new
  kinds of config file or reference fields.
