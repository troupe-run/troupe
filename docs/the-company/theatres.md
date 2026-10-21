---
title: Theatres
description: What a theatre is.
status: written
prerelease: true
---

A theatre is a project directory with troupe config. It's where troupe works, and everything troupe knows about it
lives inside it, in git, on your machine: its config, its history and its decisions. There's no hosted service
holding any of it.

## Finding the theatre

Every troupe command runs in a theatre: the nearest directory, from where you are upwards, that holds `.troupe/`.
So you can run troupe from anywhere inside your theatre, as you would git. troupe never makes a theatre for you:
without one, a command fails with `theatre.not-found` and changes nothing. [Your first
theatre](../opening-night/first-theatre.md) sets one up.

## What lives in `.troupe/`

```text
.troupe/
  .gitignore         keeps local/ out of git
  .gitattributes     keeps git from changing troupe's files' line endings
  events/            the theatre's history: committed
  local/             this clone's own state: never committed
```

- **`events/` is the history.** Everything troupe does is recorded here as [events](../prompt-book/events.md),
  appended one per line and never rewritten. Each command writes its own file, and a branch never writes another
  branch's, so two people's history merges in git without conflicts.
- **`local/` belongs to this clone,** such as which runs are going right now and large files like transcripts,
  which lineage refers to by hash instead of putting them in git.
- **`.gitignore` and `.gitattributes` keep your lines.** troupe adds the lines it needs to the end, with a comment
  saying why, and never changes or removes one that's there. If you delete one of troupe's lines, troupe adds it back
  the next time it writes, because it needs it.
- **Nothing is made until it's needed.** troupe writes these the first time it records something. Reading never
  changes your history.

Today a theatre has to be under git. troupe can also record to plain files with no branches, but nothing can choose
that yet ([Your first theatre](../opening-night/first-theatre.md#put-it-under-git)).

## Config

A theatre's config lives in it, under `.troupe/`:

```text
.troupe/
  actors/
    tester.yaml      the actor tester: its runner, the runner's options, and its effect check
    tester.md        tester's character: who it is, in its own words
```

- **Convention over configuration.** A file's name is what it defines: `actors/tester.yaml`, with
  `actors/tester.md` for its character, is the actor `tester`.
- **Changes are events.** `troupe config set` and `troupe config unset` record each change in the theatre's history,
  with who made it and why, and troupe writes the files from those changes. `troupe config get` shows what config
  holds. See [Hand-edit config safely](../stagecraft/hand-edit-config.md) for what happens if you edit a file
  yourself.
- **Every file names its schema,** so your editor can check it, and every kind of file has its own
  [schema](../prompt-book/config-schema.md).
- **Branches merge.** Config changes made on two branches are combined when the branches are merged, and troupe asks
  you to resolve the ones that conflict.
- **Your theatre's config lives only in the theatre.** troupe's own per-user settings live in `~/.troupe/`, and
  never layer over a theatre's config.
- **[Guests](guests.md)** will keep their own files in their own places, with their own schemas, so they can't
  reshape troupe's.

Whether policy has its own files, apart from the rest of config, is open in
[#8](https://github.com/troupe-run/troupe/issues/8).
