---
title: Your first theatre
description: Setting up troupe in a project directory.
status: written
prerelease: true
---

A theatre is a project directory with troupe config: the place troupe works, and where it keeps its history. This
page sets one up in an existing project directory, step by step.

## Make the theatre

troupe never makes a theatre for you. A command finds its theatre by looking for a `.troupe/` directory, from where
you are upwards, and fails with `theatre.not-found` when there isn't one. So today, you make one by hand:

```sh
cd my-app
mkdir .troupe
```

There's no setup command yet, and whether there'll be one isn't decided: it's an open question on
[#60](https://github.com/troupe-run/troupe/issues/60), which brings config.

## Put it under git

Today troupe reads and records a theatre through git, so the theatre needs to be under git: run `git init`
first if it isn't. A fresh git repository with no commits is fine. Every event troupe records notes the
branch and commit it was made on, and commit `.troupe/` with the rest of your files: troupe sets up what git needs
the first time it writes.

troupe can also work without git, recording to plain files with no branches, but nothing can choose that yet:
config will ([#60](https://github.com/troupe-run/troupe/issues/60)). Which of the two a non-technical user should
get is an open question, in [#121](https://github.com/troupe-run/troupe/issues/121).

## What troupe writes

troupe writes into `.troupe/` the first time it records something. Reading never changes your history.

```text
.troupe/
  .gitignore         keeps local/ out of git
  .gitattributes     keeps git from changing the event files' line endings
  events/            your theatre's history: commit it
  local/             this clone's own state, never committed
```

The history in `events/` is append-only text, one event per line, so two people's history merges in git without
conflicts. [Theatres](../the-company/theatres.md) says more about what lives here.

## Config, when it comes

Config will live in your theatre too, laid out by convention: the file's name is what it defines, so
`actors/tester.yaml` (with `actors/tester.md` for its prompt) is the actor `tester`. Every config file names its
schema, so your editor can check it as you type. You'll change config with `troupe config set`, which records each
change as an event, or by editing the files by hand. See [Hand-edit config safely](../stagecraft/hand-edit-config.md)
and the [config schema](../prompt-book/config-schema.md).

Next: [your first performance](first-performance.md).
