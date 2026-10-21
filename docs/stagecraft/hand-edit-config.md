---
title: Hand-edit config safely
description: Editing config by hand.
status: written
prerelease: true
---

You change config with `troupe config set` and `troupe config unset`. Each records a change, with who made it and
why, and troupe writes the files under `.troupe/` from those changes: `actors/tester.yaml` for the actor `tester`,
with `actors/tester.md` for its character. The files are there for you to read, and to review as diffs.

## Today: troupe writes the files, and never reads them back

troupe doesn't read your edits to a config file yet. That comes next
([#119](https://github.com/troupe-run/troupe/issues/119)). Until then:

- **A file you edited is never overwritten.** Before replacing a config file, troupe checks it's one troupe wrote.
  If it isn't, the command stops with `config.file-not-troupes`, names the file, and changes nothing. To go on, undo
  your edit (`git restore` the file) and make the change with `troupe config set`.
- **`troupe flush --force` replaces it anyway,** and keeps a copy of what it held first: the output names the file and
  where its bytes are kept.
- **A config file you deleted is written again** from config, with a notice. Config holds everything the file held,
  so nothing is lost.
- **Your edit doesn't change config.** `troupe config get` shows what config holds, whatever the file says.

Every command that uses config makes the files what config says first, so a run never uses one thing while its file
shows another. `troupe flush --rehearse` shows what it would change, and changes nothing.

## Your formatting will be kept

When troupe reads hand edits back and writes a file you've edited, it will change only what it must, and leave the
rest as you wrote it: your comments, your order and your formatting. That's decided, and comes with
[#119](https://github.com/troupe-run/troupe/issues/119).

## Your editor can help

Every config file names its [schema](../prompt-book/config-schema.md) at troupe.run, so an editor that knows JSON
Schema completes and checks the file as you type. troupe.run serves the schemas from
[website#30](https://github.com/troupe-run/website/issues/30) onwards. An actor's options depend on its runner, so
the file's schema can't check them: `troupe config set` does, against the runner's own options schema.

## When the sweep lands

What's decided about reading hand edits back ([#119](https://github.com/troupe-run/troupe/issues/119)):

- **Before each command, troupe sweeps the config files** for edits it didn't make, and records each meaningful one
  as a change with its lineage. It doesn't watch the files while you work.
- **It records the net change.** If you change a value from 3 to 5 and then to 7 between two commands, the history
  says 3 → 7. If you change it to 5 and back to 3, nothing is recorded.
- **A half-saved file isn't read as a change.** An editor's empty or partial file, mid-save, must never become
  "delete everything".
- **Who made a hand edit often can't be known,** and troupe says so in its [lineage](../the-company/lineage.md)
  rather than guessing.
- When an edit troupe recorded is then abandoned, because the file went back to what it was through `git restore` or
  a stash, troupe will ask whether to keep or drop the events it left behind, and never drop them without your
  answer ([#45](https://github.com/troupe-run/troupe/issues/45)).

## Branches

Config changes made on two branches are combined when the branches are merged. If both changed the same value
differently, or together they make config invalid, troupe refuses to use config until you resolve it: `troupe
config get` shows both sides, and one `troupe config set` that sets every value in conflict resolves it. troupe
never merges inside a value, such as two edits to one character: the whole value is one person's or the other's
([#135](https://github.com/troupe-run/troupe/issues/135),
[#136](https://github.com/troupe-run/troupe/issues/136)).
