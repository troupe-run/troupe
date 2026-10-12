# protocol

Language-neutral contracts between troupe and everything that talks to it: the CLI, the run server and UIs
(the client protocol), and out-of-process plugins (the plugin protocol). They are written as
[JSON Schema](https://json-schema.org/) (draft 2020-12), so a surface or plugin in any language can use them.

| Schema | What it defines |
|---|---|
| [`schemas/error.schema.json`](schemas/error.schema.json) | The structured error every surface renders: a stable `code`, the `problem`, the `fix`, and an optional `path` and `details` |
| [`schemas/notice.schema.json`](schemas/notice.schema.json) | Something a person should know while troupe works, such as a wait or a retry: the same fields as an error, with its own codes |
| [`schemas/runner/`](schemas/runner/) | The runner contract: JSON-RPC 2.0 over a runner's standard input and output, one message per line. One schema per message (`initialize`, `run/start`, `run/event`, `run/transcript`, `run/cancel`, `shutdown`), the error response, and `message.schema.json`, which accepts any line either side may send. [docs/runners.md](../docs/runners.md) explains how to write a runner |

## Source of truth

The JSON Schema here is the source of truth (decision
[#7](https://github.com/troupe-run/troupe/issues/7)). Once there is enough schema to justify a generator,
Python types are generated from it. Until then, the Python types that mirror a schema are checked against it by
tests, so the two can't drift.
