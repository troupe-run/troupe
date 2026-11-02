# troupe-plugin-sdk

The public API troupe's plugins build against. It's one small package, standard library only, of plain functions and
immutable values, so a plugin that uses it inherits nothing else and runs however it likes. It imports nothing from
`troupe`. Core depends on it for the same types, and plugins depend on it, never on core (decision
[#239](https://github.com/troupe-run/troupe/issues/239)).

It holds:

- **The runner contract's types** (`troupe_plugin_sdk.runner`): every message of
  [the runner contract](../../contributing/runners.md), its protocol versions and its JSON-RPC error codes, on a strict
  message base (`troupe_plugin_sdk.messages`). The JSON Schemas in [`protocol/schemas/runner/`](../../protocol/schemas/runner/)
  are the source of truth, and the tests check every type against them.
- **Running a model's tool calls** (`troupe_plugin_sdk.tools`), for a runner whose engine returns tool calls rather than
  carrying them out itself, such as a local model or a Chat Completions API.

[#58](https://github.com/troupe-run/troupe/issues/58) grows it into the full plugin SDK, with JSON-RPC framing and a
server loop.

## Tools

A runner offers its model these tools, and gives each call the model makes to `Tools.run`. They're file tools only.
There's no shell, because nothing on the local stage would contain it.

<!-- The table is checked against the tool definitions by tests/test_readme.py. -->

| Tool | Input | What it does | Effect it needs |
|---|---|---|---|
| `Read` | `file_path`, `offset`, `limit` | Returns a text file's lines, each with its number | none |
| `Write` | `file_path`, `content` | Creates or replaces a whole file | `write` |
| `Edit` | `file_path`, `old_string`, `new_string`, `replace_all` | Replaces text that occurs exactly once (or every occurrence) | `write` |
| `Glob` | `pattern`, `path` | Lists the files whose paths match a pattern | none |
| `Grep` | `pattern`, `path`, `glob` | Returns the lines matching a regular expression, as `path:line:text` | none |
| `Delete` | `file_path` | Deletes one file | `delete` |
| `Move` | `source`, `destination` | Moves one file; the destination must not exist | `move`, for both |

`Read`, `Write`, `Edit`, `Glob` and `Grep` are named as Claude Code names them. `Delete` and `Move` are troupe's own.

Every path is relative to the workspace, with `/` between its parts, and the same rules apply on every platform. A
path that's absolute, uses `..`, a `\`, a `:` or a reserved Windows name, leads into `.git`, or leads out of the
workspace through a link is refused. The effects are checked on the path a call would actually change, after links.

## Effects

An actor's declared effects are three lists of workspace-relative path patterns:

```python
from troupe_plugin_sdk.effects import Effects

effects = Effects(write=("src/**", "docs/*.md"), delete=("build/**",), move=("drafts/**",))
```

In a pattern, `*` matches within one part of a path, `?` matches one character, and `**`, as a whole part, matches
any number of parts: `src/**` matches `src/a.py` and `src/pkg/b.py`, but not `src` itself. `Glob` uses the same
patterns. A malformed pattern raises a `PatternError` naming the effect and the pattern.

With nothing declared (`Effects()`), an actor is read-only. Deleting and moving are declared apart from writing,
because they're more destructive. A call the effects don't allow is an error result naming the tool, the path and
the effect it needs, and nothing changes. The check isn't enforcement: the runner is still a process on the host, so
troupe records the local stage's effects as unenforced.

## A runner's tool loop

```python
from pathlib import Path

from troupe_plugin_sdk.effects import Effects
from troupe_plugin_sdk.events import EventNumbering
from troupe_plugin_sdk.tools import Tools

tools = Tools(Path(workspace), Effects(write=("out/**",)))
numbering = EventNumbering(run_id, event_max_bytes, next_seq=1)  # after init, seq 0

offered = tools.definitions()  # each tool's name, description and input schema
# ... ask the model, offering `offered`; for each tool call in its reply:
step = tools.run(call_id, name, arguments, numbering)
for event in step.events:  # tool_call, then tool_result
    send(event)
reply_to_model(call_id, step.output)
```

`arguments` is the call's input as an object, or as the JSON text of one. An unknown tool, malformed input, a refused
path or effect, and a call that fails are each an error result the model can read and act on. None of them ends the
run. The two events are numbered from the same counter as the runner's other events, and fitted to `eventMaxBytes`.

## Limits

Each limit has its default in `troupe_plugin_sdk.defaults`. A runner may lower any of them with `ToolLimits`, never
raise them. A result that's cut says so, and says how to get the rest. Only regular files are read: a
directory, a pipe or a device is an error result for `Read` and `Edit`, and skipped by `Grep`.

The limits bound what a call returns, not how long it takes. `Grep` runs the model's regular expression with
Python's `re`, which can't be interrupted, so an expression that backtracks badly can stall the call. The size
limits bound the text each search sees, and troupe's run timeout bounds the run: a runner that stalls is stopped,
never waited on silently.

| Limit | Default | What it caps |
|---|---|---|
| `read_max_bytes` | 256 KiB | The file text `Read` returns in one call |
| `read_max_lines` | 2000 | The lines `Read` returns in one call |
| `file_max_bytes` | 16 MiB | The largest file `Read` and `Edit` load; a larger one is an error result |
| `glob_max_paths` | 1000 | The paths `Glob` returns |
| `grep_max_matches` | 500 | The lines `Grep` returns |
| `grep_file_max_bytes` | 1 MiB | The largest file `Grep` searches |
| `summary_max_bytes` | 4096 | Each run event's `inputSummary` or `outputSummary` |
