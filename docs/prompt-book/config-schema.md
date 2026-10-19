---
title: Config schema
description: The full config schema, generated from its JSON Schema.
status: written
prerelease: true
---

troupe's config isn't built yet: it arrives with [#60](https://github.com/troupe-run/troupe/issues/60). Until it
does, `troupe perform` takes what config will hold on its command line (see the [CLI](cli.md)). This page says what
has been decided about the schema, and lists the schema itself once it exists.

## What's decided

- **JSON Schema is the source.** Every file troupe reads has a JSON Schema in troupe's `protocol/`, and troupe's
  own types are generated from it, so the schema and the code can't disagree.
- **One schema per kind of file.** Config is laid out by convention: the filename is the identity, so
  `actors/tester.yaml` (with `actors/tester.md` for its prompt) is the actor `tester`. Each kind of file has its
  own schema, matched by its path.
- **Every config file names its schema** with `$schema:`, so your editor can complete and check it as you type.
  troupe keeps a copy of its schemas in `.troupe/local/schemas/`, outside git, and files point there by a relative
  path that works on every clone.
- **Schemas are strict.** Every object is closed and every value is typed, so a misspelt key or a value of the
  wrong kind is an error that names it, never ignored.
- **The first kind is the actor:** its runner, the runner's options, and the effect check.

How a change addresses one value, how schemas are published at a URL, and how they're versioned aren't decided
yet: they're part of [#60](https://github.com/troupe-run/troupe/issues/60)'s design.

## The schema

<!-- generated: config (from protocol/schemas/config/; regenerate with `uv run scripts/docs_reference.py`) -->
There is no config schema yet: config arrives with [#60](https://github.com/troupe-run/troupe/issues/60), and this section is generated from its schemas when it does.
<!-- end generated: config -->
