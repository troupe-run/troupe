---
title: Hand-edit config safely
description: Editing config by hand.
status: written
prerelease: true
---

You change config by editing the files under `.troupe/`, or with `troupe config set` and `troupe config unset`.
Either way, troupe records each change as an event, and the files are written from those events: `actors/tester.yaml`
for the actor `tester`, with `actors/tester.md` for its character, and `runtimes/<name>.yaml` for a runtime.

## How troupe reads your edits

Before each command that uses config (`troupe perform`, `troupe config set`, `unset` and `get`, and `troupe sync`),
troupe sweeps the config files for edits it didn't make, and records each meaningful one as a change
([#119](https://github.com/troupe-run/troupe/issues/119)). It doesn't watch the files while you work.

- **Only a change in values counts.** A comment, a new order of keys, different quoting or indentation: none of that
  is a change, and troupe leaves your file as you wrote it.
- **It records the net change.** If you change a value from 3 to 5 and then to 7 between two commands, the history
  says 3 → 7. If you change it to 5 and back to 3, nothing is recorded.
- **Each edited file is one change, by an unknown author.** Who edited a file can't be known, so troupe says so in
  its [lineage](../the-company/lineage.md) rather than guessing: not you, even if your name is set, and not whoever
  committed it. The change names the file and its content before and after. Its output says what it recorded.
- **The file wins.** If you put a file back with `git restore`, or check out an older version of it, that's an
  edit too, and troupe records it. Your restore stands.
- **Adding a file adds what it holds; deleting one removes it.** Delete `actors/tester.md` and the character is
  removed; delete both of `tester`'s files and the actor is. troupe only counts a file as deleted if it saw it in
  this clone before: a file this clone never had, such as one never committed, is written again from config.

`troupe sync` does the sweep on its own, and makes every file say what config says. `troupe sync --rehearse` shows
what it would record and write, and changes nothing.

## What troupe won't read

A file that isn't config is refused, and nothing from any file is recorded until it's fixed. The message names the
file and what's wrong, never repeating your value:

- **A file that's present but empty**, or holds nothing but its schema lines, is refused, never read as "delete
  everything". An editor can leave a file like that for a moment while it saves. To remove something, delete its
  file.
- **A file that doesn't parse**, or that YAML could read more than one way (anchors, aliases, tags, merge keys), is
  refused with the line and column.
- **A value config wouldn't accept**, such as a misspelt field or an option the actor's runner doesn't define, is
  refused as `troupe config set` would refuse it.
- **A file that changes while troupe reads it** is read again, then refused if it keeps changing.

`troupe sync --force` replaces a file troupe can't read with what config says, and keeps a copy of what it held:
the output names the file and where its bytes are kept (`.troupe/local/artifacts/`, never committed).

## Your formatting is kept

When troupe writes a file you've edited, because a command changed config, it changes only what it must: the values
that changed, and nothing else. Your comments, your order and your formatting stay as they were. A new key goes
where the [schema](../prompt-book/config-schema.md) puts it among the keys already there. If troupe couldn't write
the change without changing anything else, it writes nothing and says so (`config.write-back-failed`).

## Your editor can help

Every config file names its [schema](../prompt-book/config-schema.md) at troupe.run, so an editor that knows JSON
Schema completes and checks the file as you type. troupe.run serves the schemas from
[website#30](https://github.com/troupe-run/website/issues/30) onwards. An actor's options depend on its runner, so
the file's schema can't check them: troupe does, when it reads the file.

When an edit troupe recorded is then abandoned, because the file went back to what it was, history shows the change
and the change back. Keeping or dropping those is [#45](https://github.com/troupe-run/troupe/issues/45).

## Branches

Config changes made on two branches are combined when the branches are merged. If both changed the same value
differently, or together they make config invalid, troupe refuses to use config until you resolve it: `troupe
config get` shows both sides, and setting every value in conflict resolves it: in the files, with `troupe config
set`, or both in one command. A hand edit that resolves a conflict is named in the output, with the value it took,
so nothing is resolved without you seeing it; an edit that sets only some of the conflicting values is kept in
your file, not recorded, until the rest are set. troupe
never merges inside a value, such as two edits to one character: the whole value is one person's or the other's
([#135](https://github.com/troupe-run/troupe/issues/135),
[#136](https://github.com/troupe-run/troupe/issues/136)).

git merges the files under `.troupe/` as text, so when both branches changed the same actor it may stop with a
conflict in `actors/<name>.yaml` or `actors/<name>.md`, or merge the two versions' lines into text troupe never
wrote. Either way, troupe checks which versions git made the file from. When each of them is one troupe wrote, the
file can't hold anything of yours, and troupe writes it again from the merged config
([#141](https://github.com/troupe-run/troupe/issues/141)):

1. Run `troupe config get` to see whether config has a conflict too. If it does, one `troupe config set` that sets
   every conflicting value resolves it, and writes the file. If it doesn't, `troupe sync` writes the file.
2. `git add` the file and commit the merge. Or turn on the setting `mark_merges_resolved`, and troupe marks the file
   resolved in git for you, as `git add` would, so you only commit the merge
   ([#156](https://github.com/troupe-run/troupe/issues/156)):

   ```sh
   export TROUPE_SETTING_MARK_MERGES_RESOLVED=true
   ```

   It's off by default. With it on, troupe stages exactly the file it wrote, and nothing else: not a clean merge's
   file, not one it didn't need to write, not a file you forced past with `--force`, and never one with a side
   troupe didn't write. Policy can forbid it (`TROUPE_POLICY_ALLOW_MARK_MERGES_RESOLVED=false`), and then troupe
   leaves git's index alone and says so. Its message always says whether it marked the file, and if not, why not.

troupe keeps a copy of what the file held before replacing it, in case you'd started resolving it by hand. Its
message gives the copy's hash, and the copy is in `.troupe/local/artifacts/`, which is never committed.

Only `troupe sync`, or a `troupe config set` that writes the file or resolves config's conflict, replaces it. Any
other command that uses config, such as `troupe perform`, refuses until you've run one of them, so a file you're
editing never changes under you.

Once you've resolved a file yourself, with every conflict marker gone, or taken a side with `git checkout --ours` or
`--theirs`, it's your edit: troupe reads it back like any other, and it resolves the conflicts it sets.

troupe refuses a file that still has conflict markers in it when one side of the conflict isn't a version troupe
wrote, because someone edited it by hand on that branch. Take one side (`git checkout --ours` or `--theirs`, as the
message says) or resolve the markers yourself, and run `troupe sync`; or run `troupe sync --force`, which keeps a
copy.
