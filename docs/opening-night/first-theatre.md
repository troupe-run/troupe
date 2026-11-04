---
title: Your first theatre
description: Setting up troupe in a project directory.
status: written
prerelease: true
---

A theatre is a project directory with troupe config: the place troupe works, and where it keeps its history. This
page sets one up in an existing project directory, step by step.

## Make the theatre

In the directory you want troupe to work in:

```sh
troupe init
```

A command finds its theatre by looking for a `.troupe/` directory, from where you are upwards, and fails with
`theatre.not-found` when there isn't one. `troupe init` makes one, in the directory you're in. It refuses where
there's a theatre already, here or above, and it refuses outside a git repository, naming `git init` (see below).
Add `--rehearse` to see what it would make, and make nothing.

`troupe init --audition` also defines a working example actor, `lead`, that runs Claude Code, and prints what to run
next. `--runner scripted` makes one that runs offline with no account instead. [Your first
performance](first-performance.md) starts there.

## Put it under git

Today troupe reads and records a theatre through git, so the theatre needs to be under git: run `git init` first if
it isn't, or `troupe init` refuses. A fresh git repository with no commits is fine to start with, but an actor's run
works from your latest commit, so you'll commit before your first performance. Every event troupe records notes the
branch and commit it was made on, and commit `.troupe/` with the rest of your files: `troupe init` sets up what git
needs.

troupe can also work without git, recording to plain files with no branches, but nothing can choose that yet:
config will ([#60](https://github.com/troupe-run/troupe/issues/60)). Which of the two a non-technical user should
get is an open question, in [#121](https://github.com/troupe-run/troupe/issues/121).

## What troupe writes

`troupe init` writes `.gitignore` and `.gitattributes`, and troupe writes the rest the first time it records
something. Reading never changes your history.

```text
.troupe/
  .gitignore         keeps local/ out of git
  .gitattributes     keeps git from changing troupe's files' line endings
  actors/            each actor's config, written from config: lead.yaml, and lead.md for its character
  events/            your theatre's history: commit it
  local/             this clone's own state, never committed
```

`actors/` is there once an actor is defined, which `troupe init --audition` does. The history in `events/` is
append-only text, one event per line, so two people's history merges in git without conflicts.
[Theatres](../the-company/theatres.md) says more about what lives here.

## Config

Config lives in your theatre, laid out by convention: the file's name is what it defines, so `actors/lead.yaml`
(with `actors/lead.md` for its character) is the actor `lead`. Every config file names its schema, so your editor
can check it as you type. You change config with `troupe config set`, which records each change as an event. troupe
can't read edits to the files back yet, so change config that way rather than by hand: see [Hand-edit config
safely](../stagecraft/hand-edit-config.md) and the [config schema](../prompt-book/config-schema.md). The services
runners talk to are config too, in `runtimes/`: see [Point actors at a service](../stagecraft/runtimes.md).

Next: [your first performance](first-performance.md).
