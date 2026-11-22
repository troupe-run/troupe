# Design

## Context

Config is events first (#60): `troupe config set` records a `Config.Changed`, config is worked out from the stream
(`core/config/stream.py`, `merge.py`), and the files under `.troupe/` are rendered from it (`projection.py`). Every
command that uses config flushes first. Before replacing a file, the flush checks the file is troupe's: what config
would write now, a version a `Config.Changed` or `local/config/written.jsonl` vouches for, or a merge git made only
from such versions (#141, #156). Anything else is refused with `config.file-not-troupes`. Files are staged beside their
target (`.<name>.troupe~`) before the change is recorded, so a crash is never mistaken for a hand edit (#60, D9).

#119 turns the one-way projection into a round trip. The owner's model: a meaningful hand edit becomes a change that
records events, updates the read model and writes back, and troupe's own write-back is a no-op. The owner decided
four questions on 2026-11-21 (recorded on #119): the file wins (decision 1), `troupe sync` replaces `troupe flush`
(2), `config get` sweeps (3), and a hand edit resolves a config conflict (4).

What exists to build on:

- Lineage already has the explicit `unknown` actor, `via: file`, and `vcs.source` with the file's hash before and
  after (`events/lineage.py`). `EventStore.command(actor=...)` accepts an actor without asking the identity chain.
- `changes.change()` diffs a group set whole against config and returns no entries when nothing differs, which is
  what "set a group from a file" already uses.
- `kinds.py` validates a config against each kind's schema and an actor's options against its runner's schema, and
  words each failure without repeating the value.
- ruamel.yaml's composer gives each key and value node a start and end mark (probed, see D6).

## Goals / Non-Goals

**Goals:**
- One sweep, run by every command that uses config, inside the config files' lock.
- Value-level change detection, with the mid-save guard and invalid files as refusals, never as removals.
- Lineage that never guesses who edited a file.
- Hand edits resolving conflicts, partially or with a value neither side had.
- Write-back that keeps every line it doesn't have to change, and a compare-and-swap before replacing.
- `troupe sync` in place of `troupe flush`, end to end: CLI, protocol, docs.

**Non-Goals:**
- Abandoned edits (#45) and renames (#138), which build on this.
- Watching files (#5).
- YAML anchors, aliases, tags and merge keys in config files: refused as invalid (D2). If a need appears, a
  follow-up decides how they write back.
- Reference fields and new kinds of file.

## Decisions

### D1. The sweep's place in a command

The sweep is one function in a new module, `core/config/sweep.py`. Every command that uses config calls it while
holding the config files' lock, before planning any write:

1. Finish or discard staged writes, as today (D9 of #60). A staged write a recorded change vouches for is moved into
   place first, so its target is never read as an edit.
2. Read what git says it merged under `.troupe/` (`merges(vcs)`, as today).
3. Classify each config file (D3), and read the values of each one that needs reading (D2, D4).
4. Work out each file's change against the config the stream gives (D5). If any file is refused, the whole sweep is
   refused and nothing is recorded (all or nothing across files).
5. Check conflicts across the batch (D8).
6. Record (D7), then go on with the command as today, with the swept config.

`sync_files` (run by `perform` and `record_change`) and the `flush` method are replaced by `sync(session, store, send,
*, operations=None, force=False, rehearse=False)`, which runs the sweep and the write. `config_set`, `config_unset`,
`config_get`, `perform` and `sync` all go through it, so no surface has its own path. `config get` runs only steps 1
to 6 and writes no file; it does take the lock, since it may record.

Rejected: sweeping outside the lock. Two terminals would both read the same edit and record it twice.

### D2. Reading a file's values

Each kind of file is read into the part of config it owns:

| File | Owns |
|---|---|
| `actors/<name>.yaml` | every field of `actors.<name>` except `character` |
| `actors/<name>.md` | `actors.<name>.character`, the whole text |
| `runtimes/<name>.yaml` | every field of `runtimes.<name>` |

YAML is read with ruamel.yaml's safe loader under YAML 1.2. These are invalid (`config.file-invalid`, with the rule
in its details):
- a syntax error (with its line and column);
- a duplicate key;
- an anchor, alias, explicit tag or merge key;
- a top level that isn't a mapping;
- a null anywhere (config never holds null).

`$schema` is read and checked, not kept as a value. When present, it must name the file's own kind (the schema's
pattern), or the file is invalid. When absent, that's an absent input, so it's allowed, and write-back doesn't add it
(D6). The `.md` file is read as UTF-8 bytes, exactly. Bytes that aren't UTF-8 are invalid.

The values then go through the checks `config set` runs: the kind's schema and the runner's options schema, on the
config the change would make (`refuse_unrecordable`'s rules). They're reported as `config.file-invalid` naming the
file, not as `config.value-invalid` naming only the path, and never repeating the value.

Rejected: YAML 1.1. The renderer already quotes every string a 1.1 reader would misread (`yes`, `012`), so a file
troupe writes reads the same either way. A person's unquoted `yes` in a string field is the string `yes` under 1.2,
and a boolean field rejects it by schema.

### D3. Classifying a file

For each path in the config directories, and each path config renders:

1. **An unknown file**: refused with `config.unknown-file`, as today.
2. **Exactly what config renders now**: in line, not read. This fast path skips reading and parsing the file; the
   sweep still renders config to compare, which loads ruamel once config holds anything.
3. **A merge git made only from versions troupe wrote, still as git made it**: not read; today's merge rules apply.
   As git made it means:
   - for a clean merge, the bytes git merged;
   - for a conflicted one, the file still has conflict markers.

   A conflicted file with no markers left is the person's resolution, and is read (decision 4, "a conflict resolved
   by hand").
4. **Conflict markers with a side troupe didn't write**: refused with `config.file-not-troupes`, as today.
5. **Absent, while config holds it**: a removal (D4).
6. **Anything else**, including an older version troupe wrote (decision 1): read.

The one change from today is step 6. "A version troupe wrote" no longer makes a file stale and safe to overwrite. It
makes it a file whose values may differ, so it's read.

### D4. Additions, removals and the mid-save guard

- A file config doesn't hold, of a known kind, adds what it holds.
- **A missing file is a removal only if this clone had it at its last sync** (refinement found while wiring, agreed
  through the orchestrator on 2026-11-22). Each sync records the config files there are in
  `.troupe/local/config/present.json` (clone-local, out of git). A file that was there and is gone, deleted by hand
  or by a `git pull` with no matching events, is a removal, and its `config.hand-edit-recorded` notice says it came
  from the file going missing. A file this clone never had, such as one never committed or gitignored while files
  were a disposable projection, is written again from config, as before #119. A missing or unreadable record counts
  as none, never as "all deleted"; an unreadable one is named (`config.present-unreadable`).
- An absent `.md` whose character config holds removes the character.
- An absent `.yaml` whose actor config holds, with its `.md` absent too, removes the group `actors.<name>`. With the
  `.md` still there, the file is invalid: an actor needs its `.yaml` (the schema requires `runner` and `expect`).
- An absent runtime file removes the group `runtimes.<name>`.
- **A present file with no values is refused** (`config.file-invalid`, rule `empty`): a 0-byte file, a `.md` with no
  bytes, or a YAML mapping with no key but `$schema`. A present file is never read as removing its group. Removal is
  only by deleting the file. That covers an editor's truncate-then-write. The schema covers a partial actor file
  that lost `runner` or `expect`.
- **A file that changes while it's read is read again.** The sweep stats the file before and after reading it,
  comparing size, modification time in nanoseconds and file id (inode, or the Windows file index, through the
  platform seam). On a difference it pauses and reads again, up to `config_read_attempts` times (default 3, pause
  `config_read_retry_seconds`, default 0.05; both in `core/defaults.py`). Then it refuses with
  `config.file-changing`. This narrows the partial-save window to the instant of a command boundary. It can't close
  it, since an editor can write between reads. A wrong partial read is still recoverable: the earlier values are in
  the events, and the next sweep records the rest.

### D5. What a file changes

A file's change is `changes.change()` applied to the group it owns, set whole from the file's values, restricted to
the fields it owns (an actor's `.yaml` never touches `character`). So:
- equal values give no entries, and nothing is recorded (no loop, D9);
- a value inside a group is set by its own entry, and a list is replaced whole (#135);
- a removed key is unset.

Each file with entries becomes one `Config.Changed`. Its `files` holds `{path, hash}` of the bytes read, or `{path}`
for a removal, so the file is a version a change vouches for. That keeps #141's merge rules working on files people
edited and committed on their branches.

Comparison is against the config the stream gives before the sweep. With conflicts, that's the merged config, whose
conflicting values show the value the history before the lines worked out. D8 says how such paths count.

### D6. Surgical write-back

Probe (2026-11-21): loading a file with ruamel's round-trip mode and dumping it again isn't byte-preserving:
- it re-indents block sequences (`  - x` becomes `- x`);
- it collapses `runner:   scripted` to one space;
- an inserted key lands after the comment above the key it's inserted before, because comments attach to the
  previous node.

So write-back splices text by node spans instead of dumping:

- Compose the file (the composer's nodes carry start and end marks), and walk it beside the target values.
- **A changed scalar, or a list replaced whole**: replace the value node's span with the value rendered by today's
  representer, so quoting rules are the same. A block sequence's end mark swallows the blank lines and comments that
  follow it, so its span is trimmed to the end of its last item's line. A block list is rendered at the indentation of
  its existing items, or two spaces past the key's when it had none.
- **A changed group** (`options`, `effects`, a runtime's `prices`): recurse into it, key by key. A group written in
  flow style (`{a: 1}`) is replaced whole, in flow style.
- **A new key**: insert `key: value` lines after the end of the line of the last sibling that comes before it in the
  file's order. At the top of an actor or runtime file that's the schema's order (`FIELD_ORDER`), and inside a group
  it's sorted order, as the renderer writes it. Use the sibling's indentation. With no sibling before it, insert
  before the first sibling.
- **A removed key**: delete from the start of its key's line to the end of its value's last line. Comment lines above
  it stay, since nothing says they belong to it.
- **New lines use the file's own line ending** (CRLF if its first line ends so).
- **An `.md` file is replaced whole**, as a value is.
- **A file troupe makes new is rendered whole, as today.**

**Verify before staging:** the spliced bytes are parsed (D2) and must give exactly the target values. If they don't,
the command is refused with `config.write-back-failed`, naming the file and saying that `troupe sync --force` rewrites
it whole, keeping a copy. Nothing is recorded, because write-back is computed before recording (staging order, #60
D9). A wrong file is never written, and formatting is never silently lost.

The property test generates formatted actor files (comments, blank lines, key orders, indentations, quoting styles,
flow and block lists) and random changes. It checks that every line outside the changed keys' spans is byte for byte
the same, and that the result reads as the target.

### D7. Lineage and recording

One sweep is one `Command` with `actor=Actor.unknown()`, `via="file"` and no reason, so its changes share a change id
(cause: that command). Each file's `Config.Changed` gets lineage with `vcs.source`:
- `path`: `.troupe/<path>`;
- `before`: the hash of the bytes troupe last had for the path, which is the file rendered from config before the
  sweep (absent if config rendered no file);
- `after`: the hash of the bytes read (absent for a removal).

`before` is what troupe last saw, so the net change is visible, not a guess at an earlier save.

`EventStore.record_with_lineage` takes one lineage for a batch. It gains a form that takes a lineage per event, still
all or nothing, so one batch can hold:
1. the settle (if the stream forked);
2. the sweep's changes;
3. the command's own change.

The sweep's changes and the command's own are checked together and recorded in one batch, with or without a conflict
(D8). So a command whose own change is refused, such as a `config set` that breaks a rule, records none of the hand
edits either. Nothing is lost: they stay in the files, and the next command sweeps them again. Only `config get`
records the sweep's changes on their own, since it has no change of its own.

The lineage spec says a change id is shared by one command's events. The sweep counts as a command of its own (delta
on `lineage`), so a person's change and an unknown author's never share a change id. A conflict listing names them
apart, and #45 can find a hand edit's events by change id.

Rejected:
- **The person running the command as the author.** That's a guess; TROUPE_ACTOR names who ran the command, not who
  edited the file.
- **git blame.** Uncommitted edits have none, and a committed one names whoever committed, who may not have edited it.
- **One `Config.Changed` per sweep.** `vcs.source` names one file, so a multi-file change would lose which file
  each entry came from.

### D8. Hand edits and conflicts

While the merged config has conflicts:

- Each file the sweep reads (D3 step 6, which includes a file the person took a side of with `git checkout --ours`
  or `--theirs`, and a conflict resolved by hand) sets every conflicting path it owns to the value it holds, as a
  `config set` of that value would. This needs no forcing: config shows a conflicting path at the value the history
  before the lines worked out, which neither side holds, so a side's value or a third value always gives an entry.
  The one value that gives none is that earlier value itself, exactly as with `config set`. A conflicting value
  whose file was deleted is unset.
- **Every conflict the sweep resolves is named** (owner, 2026-11-21). Two conflicting values in one edited file are
  both resolved, since the file wins, so the person may resolve a value they didn't touch. Each resolved value gets
  a `config.conflict-resolved` notice, streamed as a `NoticeUpdate` from every command, sync included. It names the
  path, the file, the value taken (or `unset`), and the conflicting changes' ids. A rehearsal reports the same,
  saying it would. The notice is catalogued in `protocol/schemas/notice.schema.json`, so it travels in the shared
  notice shape; client-protocol needs no change.
- A file exactly what config renders now (D3 step 2) isn't read, so it resolves nothing. A person who wants the value
  the history before the lines worked out uses `troupe config set`.
- An untouched merge git made (D3 step 3) resolves nothing.
- The resolution check is today's rule: the batch must set or unset every conflicting value. It runs on the union of
  the sweep's entries (with the conflicting paths added as above) and the command's operations (`config set`'s, if
  that's the command).
  - If the union resolves everything, one batch records the settle, the sweep's changes and the command's change.
  - If it doesn't, `config.conflict` names what's left and nothing is recorded. The edited files stay as the person
    left them, unrecorded.
- `config get` with a partial resolution records nothing, shows the conflicts as today, and adds the notice
  `config.hand-edit-unrecorded`, naming each file and the conflicting values still unset.
- A file's own values that aren't in conflict are recorded with it, as `config set` records extra values with a
  resolution.

The conflicting values are compared as whole values (#135), so a list edited inside counts as setting the whole list.

### D9. No loop

troupe's own writes read back as in line:
- a file troupe renders whole is D3 step 2;
- a spliced file reads back as the target values (D6's verification), so D5 gives no entries.

The test runs every command twice on a hand-formatted theatre, and checks that the second run records nothing and
writes nothing.

### D10. Compare-and-swap before replacing

The sweep keeps the bytes it read for each path. Holding the lock, just before each atomic replace or removal, the
file is read again and compared. If it changed, the command is refused with `config.file-changing`, and staged writes
are discarded (if the change was already recorded, the staged file stays and the next command's step 1 finishes it,
as for a crash). The lock doesn't bind editors, so a save between the compare and the rename can still be lost to the
rename. The window is the one rename call. The refusal covers everything before it.

### D11. `troupe sync`, and reporting hand edits

- `protocol/schemas/client/flush-{request,result,update}.schema.json` become `sync-*`, and the method is `sync`. The
  request keeps `force` and `rehearse`. The result adds `edits`: per file, its path, the change id and the entries
  recorded (or, rehearsed, that would be).
- Every other command reports each recorded hand edit as the notice `config.hand-edit-recorded` (path, change id,
  number of entries), streamed as a `NoticeUpdate`. That needs no change to their result schemas.
- `Config.Changed`'s description stops saying one command records exactly one.
- New error codes: `config.file-invalid`, `config.file-changing`, `config.write-back-failed`. Each lands with code
  that raises it and a test (protocol_guard).
- The protocol CHANGELOG records the rename as breaking. Pre-1.0, there's no alias (decision 2).
- `--force` (D3, today's rule): replaces every file the sweep or a check refused with what config says, keeping its
  bytes. It records nothing for those files, and the sweep still reads and records the valid ones. With `--rehearse`,
  it shows both.
- Every message that says "run troupe flush" says `troupe sync`.

### D12. The first run, and docs

Per the owner's comment on #119, these say to edit `.troupe/actors/lead.md`:
- `render_init`'s character line;
- the cli scenario, now "The character is changed by editing its file";
- `docs/opening-night/first-performance.md` ("Write its character");
- `first-theatre.md`'s "Config" section;
- `docs/prompt-book/cli.md`'s `troupe init` entry.

`docs/stagecraft/hand-edit-config.md` replaces "Today: troupe writes the files, and never reads them back" and "When
the sweep lands" with how the sweep works now. Every page that names `troupe flush` names `troupe sync`, and
`contributing/config.md` describes the sweep's module and D3's order.

## Risks / Trade-offs

- **A file missing for a reason other than a person deleting it is read as a removal.** Examples: a sparse checkout,
  or a tool that deletes and rewrites. The removal entry holds only the old value's hash. The values are in earlier
  events, so they can be recovered with `config set`, but not in one step. #45's keep or drop is the natural place to
  offer an undo. The decision (the file wins) accepts this.
- **Partial saves can't be ruled out**, only narrowed (D4). A wrong read is recorded, not lost, and the next sweep
  corrects it.
- **Span splicing meets YAML's corners** (multi-line scalars, comments inside flow collections, odd indentation).
  Verification (D6) turns any miss into a refusal, never a wrong file. The property test explores the corners.
- **Bigger lock hold.** The sweep reads every file under the lock. Config is small, and the fast path skips ruamel
  when nothing changed.
- **Windows.** File ids and nanosecond modification times go through the platform seam. CRLF files keep their line
  endings (D6). `actors/** -text` already stops git converting them.
- **The PR is large.** Per the memory on large PRs, the review is split by slice: the sweep and classification,
  write-back, conflicts, then CLI, protocol and docs. Commits follow the same slices.

## Migration Plan

Pre-1.0, no compatibility forms:
- `troupe flush` is gone.
- Scripts and docs move to `troupe sync`.
- No event changes shape: hand edits use fields lineage already has.

The infrastructure PR adding `config-hand-edits`' Purpose to `oob/troupe-spec-purposes.json` merges after this one.

## Open Questions

None. The owner settled the four on 2026-11-21. Anything the build finds that changes behaviour goes back through
the orchestrator before the code depends on it.
