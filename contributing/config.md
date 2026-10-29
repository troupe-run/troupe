# Config

A theatre's config is events: one `Config.Changed` per command that changes it, in one stream per theatre, merged
across branches. The files under `.troupe/` are a projection that troupe writes and never reads back (yet). This
page describes config as built by the `config-model` change (#60); the decisions behind it are #6 (layout), #7
(schemas), #135 (values are never merged inside), #136 (config history) and #137 (`--rehearse`).

## Events

- **One stream per theatre**, with the same id everywhere (`troupe.core.config.aggregate.STREAM`).
- **`Config.Changed`** holds `changes`, one entry per value the command changed, and `files`, every config file it
  wrote (with the hash of the bytes) or removed (with none). Its payload schema is
  [`events/config-changed.schema.json`](../protocol/schemas/events/config-changed.schema.json).
- **An entry** is `{"path": [...keys], "before": "sha256:...", "after": value}`. `before` is the SHA-256 of the old
  value's canonical JSON, absent when there was none; `after` is the new value, absent when it was removed, and never
  an object, since an object is a group of values (#135). Removing a group is one entry addressed to it.
- **`Config.Settled`** ends a fork in the config stream, recorded with the first change after a merge, in the same
  batch ([`events/config-settled.schema.json`](../protocol/schemas/events/config-settled.schema.json)).

`troupe.core.config.changes` builds entries from a command's operations (and a path changed twice in one command
records its net change); `troupe.core.config.kinds` checks config before a change is recorded.

## The merge

Config is worked out from the stream's whole history, both sides of every fork, never with the library's `load`
(`troupe.core.config.merge`):

- **Points and latest writes.** Each path an entry names is a point; the writes that cover it are the entries at it
  or at a group above it; its latest writes are those no later covering write follows.
- **Each line's net change.** A latest write's line is the covering writes behind it that the other latest writes
  don't descend from. A line whose writes are all at the point, and end where they began, drops out. When a line
  starts with concurrent writes (a fork joined inside it), it drops out only if every one of them starts from where
  it ends. Lines left that leave the point differently conflict, as whole changes.
- **Validation.** A merged config that breaks a rule is a conflict between the changes since the split that
  touched what broke it, for an actor with no conflict already.
- **Replay.** Config is every entry replayed in the history's order, leaving out the lines that dropped out and both
  sides of every conflict. Where that leaves out every latest write of a point, the writes beneath them are contested
  by the same rule, until one is left or a line stays in, so the order events arrived in never decides a value
  ([#190](https://github.com/troupe-run/troupe/issues/190)). Only the first contest's conflict is reported. A
  settling event is read as a join, never for its state.

Any conflict blocks every use of config but `config get`, until one change that sets or unsets every conflicting
value resolves it (`troupe.core.config.stream`). Reads record nothing.

## Files

`troupe.core.config.projection` renders each actor to `actors/<name>.yaml` (its schema named twice, at troupe.run
by major version; keys in the schema's order, groups' keys sorted, strings quoted so YAML 1.1 and 1.2 read them
the same) and `actors/<name>.md` (the character's text exactly). Before replacing or removing a file it checks the
file is troupe's:

| On disk | Then |
|---|---|
| What troupe would write now | nothing to do |
| A hash a `Config.Changed` recorded for that path, or this clone's record of files flush wrote (`.troupe/local/config/written.jsonl`) | written again, with `config.file-rewritten` |
| Nothing | written again, with `config.file-rewritten` |
| A file git merged (conflicted, or cleanly in the merge in progress or HEAD's merge commit) from versions troupe recorded | written again from the merged config by `troupe flush`, or by the `config set` whose change writes it or resolves config's conflicts, its bytes kept first, with `config.merge-rewritten`; refused by any other command, naming `troupe flush` |
| Anything else | refused with `config.file-not-troupes`, unless `--force`, which keeps its bytes in the artifact store |

A change stages each new file beside its target (`.<name>.troupe~`), records the event with the files' hashes, then
moves them into place with an atomic replace, all under the lock in `.troupe/local/config/`. A staged file an event
vouches for is a write a crash cut short, and the next flush finishes it; one no event vouches for is removed.

### Files git merged

git merges the files under `.troupe/actors/` as text, so a merge can leave one conflicted, or merge two versions of
it cleanly into text troupe never wrote. The VCS port's `merge_sides_under` says which versions a merge combined
into each path, and config uses that to decide whether nothing a person wrote can be in the file
(config-projection-conflicts design D2 to D4). The git adapter (`troupe_vcs_git.merges`) reads:

- **a conflicted path** from the index's stages, ours (2) and theirs (3), whatever left it unmerged: a merge, a
  rebase, a cherry-pick, a revert or a stash pop;
- **a clean merge** only in the merge in progress (`MERGE_HEAD`) or in HEAD when it's a merge of two parents, and
  only for paths whose merged blob differs from both parents'. `git merge-tree --write-tree` on the two parents
  must give that blob, with no conflict.

It uses `merge-tree` rather than `merge-file` on the base and both sides because `merge-tree` redoes the merge with
the strategy git used (ort) and the person's merge settings, handles several merge bases as the merge did, and needs
git 2.38. Matching ort with `merge-file` needs `--diff-algorithm`, which arrived in git 2.44, and Apple's bundled
git is older. A merge edited before it was committed, or made with options `merge-tree` didn't get, doesn't
reproduce, so it's refused as a hand edit is. The files adapter reports no merges.

## Notices and errors

| Code | When |
|---|---|
| `config.invalid` | A change would make config break a rule: an unknown field, an option its runner doesn't define, a missing effect check, a bad name. Names the path and the rule |
| `config.conflict` | Branches' config changes conflict, so config can't be used until they're resolved |
| `config.file-not-troupes` | A config file isn't one troupe wrote, so it won't be replaced. A conflicted file with a side troupe didn't write names that side and the side to take; a file git merged from troupe's versions, met by a command other than `troupe flush` or the `config set` that writes it, names `troupe flush` |
| `config.unknown-file` | A file in a config directory matches no kind of config file |
| `config.local-malformed` | This clone's record of the files flush wrote has a malformed line before its last |
| `schemas.plugin-missing` | A runner's package isn't installed, or ships no schemas |
| `config.file-rewritten` | (notice) A config file troupe wrote was missing or older, and was written again |
| `config.merge-rewritten` | (notice) A config file git merged from versions troupe wrote was written again from the merged config, its bytes kept first, and needs a `git add` |
| `config.waiting` | (notice) Another troupe command is writing config files, and this one is waiting |
