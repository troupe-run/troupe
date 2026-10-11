# protocol

Language-neutral contracts between troupe and everything that talks to it: the CLI, the run server and UIs
(the client protocol), and out-of-process plugins (the plugin protocol). They are written as
[JSON Schema](https://json-schema.org/) (draft 2020-12), so a surface or plugin in any language can use them.

| Schema | What it defines |
|---|---|
| [`schemas/error.schema.json`](schemas/error.schema.json) | The structured error every surface renders: a stable `code`, the `problem`, the `fix`, and an optional `path` and `details` |

## Source of truth

The JSON Schema here is the source of truth (decision
[#7](https://github.com/troupe-run/troupe.run/issues/7)). Once there is enough schema to justify a generator,
Python types are generated from it. Until then, the Python types that mirror a schema are checked against it by
tests, so the two can't drift.
