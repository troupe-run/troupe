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
### Actor

One actor's config file, .troupe/actors/<name>.yaml. The file's name is the actor's name. Its character, when it has one, is the whole of .troupe/actors/<name>.md. troupe writes this file from the theatre's config events, and every field is set with troupe config set.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `$schema` | string | No | Where this file's schema is, relative to the file, so editors can check it. troupe writes it. |
| `runner` | string | Yes | The runner that runs this actor, by name. |
| `options` | object (an extension point, filled by the runner's options schema) | No | The runner's own options, passed to it unchanged. Absent means {}. An extension point: the runner's published options schema fills it, and without one only {} validates. |
| `expect` | list of string | Yes | Files, relative to the theatre's root, that a run must create or change: each must exist after the run, and differ from before it. A file named twice is checked once. An empty list means no effect check, and has to be written. |
<!-- end generated: config -->
