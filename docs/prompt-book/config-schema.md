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
| `expect` | list of string | Yes | Files, relative to the theatre's root, that a run must create or change: each must exist after the run, and differ from before it, and each must match a write or move pattern in effects. A file named twice is checked once. An empty list means no file has to change; the run's changes are still audited against its effects. It has to be written. |
| `effects` | object (Declared effects) | No | What this actor's runs may change: write, delete and move, each a list of patterns relative to the theatre's root. Absent declares nothing, so the actor is read-only. Every path in expect must match a write or move pattern. After each run, troupe audits every change in the workspace against it. Not enforcement: only a stage that enforces effects contains a run. |
| `workspace` | one of `"worktree"`, `"theatre"` | No | Where a run works. worktree, the default when absent: the run's own git worktree at HEAD, under .troupe/local/worktrees/, whose changes reach the theatre only through troupe accept. theatre: the theatre itself, so what the run writes lands among your files at once. |
| `runtime` | string | No | The runtime this actor's runs talk to, by name: one of troupe's built-in runtimes or one in config. Only for a runner that takes a runtime; required by one that needs it. |
| `model` | string | No | The model this actor's runs use, overriding its runtime's. The person's TROUPE_RUNTIME_<NAME>_MODEL overrides both. Only with a runtime. |

### Runtime

One runtime's config file, .troupe/runtimes/<name>.yaml: a service a runner talks to. The file's name is the runtime's name. It holds only what the theatre's config sets: a built-in runtime's other fields are troupe's defaults, and the person's environment overrides any of them (TROUPE_RUNTIME_<NAME>_ENDPOINT, _MODEL, _CREDENTIAL_ENV). troupe writes this file from the theatre's config events, and every field is set with troupe config set.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `$schema` | string | No | Where this file's schema is, so editors can check it. troupe writes it. |
| `endpoint` | string | No | The base URL the runner's API is served under: http or https, a host and an optional port and path, with no user info, query or fragment. The runner adds its own paths. Required for a runtime that isn't built in. |
| `model` | string | No | The model a run uses when its actor sets none, as the service names it. |
| `credential` | object (Credential) | No | Where the runtime's credential comes from. Never the credential itself: config is committed, so it holds only a reference. |
<!-- end generated: config -->
