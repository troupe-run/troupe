---
title: Hand-edit config safely
description: Editing config by hand.
status: written
prerelease: true
---

Config isn't built yet ([#60](https://github.com/troupe-run/troupe/issues/60)). When it is, you'll be able to change it
with `troupe config set`, or by editing its files by hand. This page says what's decided about hand edits.

## troupe records what you changed

- **Before each command, troupe sweeps the config files** for edits it didn't make, and records each meaningful one
  as a change with its lineage. It doesn't watch the files while you work.
- **It records the net change.** If you change a value from 3 to 5 and then to 7 between two commands, the history
  says 3 → 7. If you change it to 5 and back to 3, nothing is recorded. History is the changes troupe saw, not every
  save.
- **A half-saved file isn't read as a change.** An editor's empty or partial file, mid-save, must never become
  "delete everything".
- **Who made a hand edit often can't be known,** and troupe says so in its [lineage](../the-company/lineage.md)
  rather than guessing.

## Your formatting is kept

When troupe writes a file you've edited, it changes only what it must, and leaves the rest as you wrote it: your
comments, your order and your formatting. That's true whichever surface made the change, the command line or a UI.

## Your editor can help

Every config file names its [schema](../prompt-book/config-schema.md), so an editor that knows JSON Schema
completes and checks the file as you type.

## Until the sweep lands

Reading hand edits back is its own change, after config ([#119](https://github.com/troupe-run/troupe/issues/119)). Until
then, troupe writes config files from its own record and never reads them back, so a file you've edited by hand is
refused, with a message naming the file and how to fix it, rather than guessed at or overwritten. When an edit troupe
recorded is then abandoned, because the file went back to what it was through `git restore` or a stash, troupe will ask
whether to keep or drop the events it left behind, and never drop them without your answer
([#45](https://github.com/troupe-run/troupe/issues/45)).
