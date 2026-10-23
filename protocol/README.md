# protocol

Language-neutral contracts between troupe and everything that talks to it: the CLI, the run server and UIs
(the client protocol), and out-of-process plugins (the plugin protocol). They are written as
[JSON Schema](https://json-schema.org/) (draft 2020-12), so a surface or plugin in any language can use them.

| Schema | What it defines |
|---|---|
| [`schemas/error.schema.json`](schemas/error.schema.json) | The structured error every surface renders: a stable `code`, the `problem`, the `fix`, and an optional `path` and `details`. It lists every code troupe can produce, each with the schema of its `details` (or none allowed) |
| [`schemas/notice.schema.json`](schemas/notice.schema.json) | Something a person should know while troupe works, such as a wait or a retry: the same fields as an error, with its own codes, each listed with the schema of its `details` |
| [`schemas/lineage.schema.json`](schemas/lineage.schema.json) | Where an event came from: actor (never absent), via, time, reason (when one was given), change (the correlation id), cause, approvals, the version-control state, and for a run, the stage it ran on and whether its effects were enforced. Every event troupe records carries it |
| [`schemas/event-record.schema.json`](schemas/event-record.schema.json) | One line of an event segment in `.troupe/events/`: the segment header (naming the session, the branch and the protocol version that wrote it), or an event with its content-hash id, parents and batch. [contributing/event-store.md](../contributing/event-store.md) explains the store. An event troupe defines has its payload checked against its topic's schema |
| [`schemas/events/`](schemas/events/) | The payload of each event troupe records, one schema per topic: a run's start, each reported run event, and its end |
| [`schemas/client/`](schemas/client/) | The client protocol: the commands and queries every surface calls the core through (`perform`, `status`, `logs`). One schema per message (each method's request, its updates while it runs, and its result), and `run.schema.json` for what they share. Transport-free: the CLI calls them in process, and a run server will serve the same messages. A request never carries a host path, a command line or a policy value. [contributing/runs.md](../contributing/runs.md) explains runs |
| [`schemas/runner/`](schemas/runner/) | The runner contract: JSON-RPC 2.0 over a runner's standard input and output, one message per line. One schema per message (`initialize`, `run/start`, `run/event`, `run/transcript`, `run/cancel`, `shutdown`), the error response and the contract's own error codes (`errors.schema.json`), and `message.schema.json`, which accepts any line either side may send. [contributing/runners.md](../contributing/runners.md) explains how to write a runner |

## Versions

The protocol is released on its own, at its own version, only when something here changes (issue
[#140](https://github.com/troupe-run/troupe/issues/140)). Each release is tagged `protocol-v<version>`, and
[`CHANGELOG.md`](CHANGELOG.md) lists what changed. Before 1.0 a breaking change bumps the minor version.
[contributing/releasing.md](../contributing/releasing.md) explains how releases happen.

troupe.run publishes each release's schemas under `https://troupe.run/protocol/<version>/`, alongside the latest
release, each major version (`/protocol/0/`) and `next`
([troupe-run/website#30](https://github.com/troupe-run/website/issues/30)). Files troupe writes name the
major-version path, such as `https://troupe.run/protocol/0/config/actor.schema.json`.

troupe never fetches a schema. The troupe package carries a copy of `schemas/`, and records which protocol release
that copy is in `troupe/protocol/version.json`, which only a protocol release pull request changes. `troupe
--version` prints it, and each event segment's header names the protocol version of the troupe that wrote it. A
record that is missing or isn't a version is the error `schemas.protocol-version-invalid`. Between releases, a
checkout of troupe records the last release, even if its schemas have changed since.

## Source of truth

The JSON Schema here is the source of truth (decision
[#7](https://github.com/troupe-run/troupe/issues/7)). Once there is enough schema to justify a generator,
Python types are generated from it. Until then, the Python types that mirror a schema are checked against it by
tests, so the two can't drift.

## Strict

Every schema here, and every schema a plugin publishes, is strict (decision [#7](https://github.com/troupe-run/troupe/issues/7)):

- **Every object is closed:** `additionalProperties: false`, or evaluated under an enclosing
  `unevaluatedProperties: false`. A map, where keys are data, types its keys with `propertyNames`.
- **Every value is typed:** by `type`, `const`, `enum`, a reference or a composition. `true` and `{}` never
  appear where a value is accepted, and every array says what its items are.
- **A place that varies is an extension point** with a closed default: `{"$dynamicRef": "#name"}`, whose
  `$dynamicAnchor` default accepts only what is safe without the outside schema. A runner's options
  (`runnerOptions`) and its own error codes (`runnerErrors`) are the two so far; a runner's published schemas fill
  them ([contributing/runners.md](../contributing/runners.md#publishing-a-runners-schemas)).
- **Codes are catalogued:** the error and notice schemas list every code, so an unlisted code doesn't validate,
  and each code's `details` keys are camelCase.

## Nulls and absent fields

A field with nothing to say is left out, never sent as `null` (issue
[#76](https://github.com/troupe-run/troupe/issues/76)):

- **Absent means "nothing to say".** Every optional property's description says what its absence means, for
  example "Absent: the file didn't exist".
- **A meaningful value beats absence.** Where a real value has its own meaning, it is used. Where one field decides
  whether another exists, the schema says so: a run's end has an `exitCode`, `transcript` and `stderr` exactly
  when the runner started, and a run summary has an `outcome` and `endedAt` exactly when the run has ended.
- **No sentinels.** `""`, `-1` and the like never stand in for absence.
- **`null` only where it says what absence can't.** The node then carries a marker:
  `"x-troupe-null": {"kind": "clear" | "external", "means": "..."}`. `clear` is "clear this" in an update, where
  `{"x": null}` and `{}` mean different things. `external` is a format troupe doesn't own requiring it. The one
  null today is external: a runner's error response has `"id": null` when the request couldn't be read, as
  JSON-RPC 2.0 requires.

`packages/troupe/tests/test_protocol_strict.py` checks every schema against these rules, and fails naming the file
and the location that breaks one. In the tests, every error and notice troupe constructs is validated against its
code's schema as it's made.

