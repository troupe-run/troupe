---
title: Config schema
description: The full config schema, generated from its JSON Schema.
status: written
prerelease: true
---

A theatre's config is a set of files under `.troupe/`, one kind of file per kind of config, and each kind has a
JSON Schema. This page lists them.

- **JSON Schema is the source.** Every file troupe reads or writes has a JSON Schema in troupe's `protocol/`, and
  troupe's own types are generated from it, so the schema and the code can't disagree.
- **One schema per kind of file.** The filename is the identity, so `actors/tester.yaml` (with `actors/tester.md`
  for its character) is the actor `tester`.
- **Every config file names its schema twice:** with a `# yaml-language-server: $schema=` comment and a `$schema:`
  key, both naming it at troupe.run by major version, such as
  `https://troupe.run/protocol/0/config/actor.schema.json`, so your editor can complete and check the file as you
  type ([website#30](https://github.com/troupe-run/website/issues/30) serves them).
- **Schemas are strict.** Every object is closed and every value is typed, so a misspelt key or a value of the
  wrong kind is an error that names it, never ignored.
- **An actor's options are its runner's.** Each runner publishes a schema for its options, and `troupe config set`
  checks an actor's options against it.

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
