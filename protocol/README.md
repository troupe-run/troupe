# protocol

Language-neutral contracts between troupe and everything that talks to it: the CLI, the run server and UIs
(the client protocol), and out-of-process plugins (the plugin protocol). They are written as
[JSON Schema](https://json-schema.org/) (draft 2020-12), so a surface or plugin in any language can use them.

| Schema | What it defines |
|---|---|
| [`schemas/error.schema.json`](schemas/error.schema.json) | The structured error every surface renders: a stable `code`, the `problem`, the `fix`, and an optional `path` and `details`. It lists every code troupe can produce, each with the schema of its `details` (or none allowed) |
| [`schemas/notice.schema.json`](schemas/notice.schema.json) | Something a person should know while troupe works, such as a wait or a retry: the same fields as an error, with its own codes, each listed with the schema of its `details` |
| [`schemas/lineage.schema.json`](schemas/lineage.schema.json) | Where an event came from: actor (never null), via, time, reason, change (the correlation id), cause, approvals, the version-control state, and for a run, the stage it ran on and whether its effects were enforced. Every event troupe records carries it |
| [`schemas/event-record.schema.json`](schemas/event-record.schema.json) | One line of an event segment in `.troupe/events/`: the segment header, or an event with its content-hash id, parents and batch. [docs/event-store.md](../docs/event-store.md) explains the store |
| [`schemas/client/`](schemas/client/) | The client protocol: the commands and queries every surface calls the core through (`perform`, `status`, `logs`). One schema per message (each method's request, its updates while it runs, and its result), and `run.schema.json` for what they share. Transport-free: the CLI calls them in process, and a run server will serve the same messages. A request never carries a host path, a command line or a policy value. [docs/runs.md](../docs/runs.md) explains runs |
| [`schemas/runner/`](schemas/runner/) | The runner contract: JSON-RPC 2.0 over a runner's standard input and output, one message per line. One schema per message (`initialize`, `run/start`, `run/event`, `run/transcript`, `run/cancel`, `shutdown`), the error response and the contract's own error codes (`errors.schema.json`), and `message.schema.json`, which accepts any line either side may send. [docs/runners.md](../docs/runners.md) explains how to write a runner |

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
  them ([docs/runners.md](../docs/runners.md#publishing-a-runners-schemas)).
- **Codes are catalogued:** the error and notice schemas list every code, so an unlisted code doesn't validate,
  and each code's `details` keys are camelCase.

`packages/troupe/tests/test_protocol_strict.py` checks every schema against these rules, and fails naming the file
and the location that breaks one. In the tests, every error and notice troupe constructs is validated against its
code's schema as it's made.

