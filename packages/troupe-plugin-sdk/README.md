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
- **The run's credential** (`troupe_plugin_sdk.credential`): `runtime_credential(params, os.environ)` gives the
  value of a runtime's credential from `TROUPE_RUNTIME_CREDENTIAL`, or `None` when the run has none, and raises
  `CredentialError` when `run/start` and the environment disagree. Send it only to the runtime's endpoint
  ([The runtime and its credential](../../contributing/runners.md#the-runtime-and-its-credential)).
- **A cost estimated from troupe's price** (`troupe_plugin_sdk.cost`): `estimate(usage, price)` gives a run's usage at
  `run/start`'s `runtime.price` in US dollars, for `result.estimatedCostUsd`, or `None` when the contract says an
  estimate is absent ([Cost: reported or estimated](../../contributing/runners.md#cost-reported-or-estimated)).
- **Compaction** (`troupe_plugin_sdk.compaction`), for a runner that holds its own conversation: which old tool
  results to replace when the run may compact, and the stub that replaces them ([Compaction](#compaction)).

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
No tool changes anything under the workspace's `.troupe`, troupe's own state, though reading it is fine.

The run's **scratch directory** is the one exception to relative paths: an absolute path inside it is accepted, and
needs no effect. Moving a file from scratch into the workspace needs `write` for its destination, and moving one out
needs `delete` for its source. With a scratch directory, each tool's description names it, so the model knows
where temporary files go.

## Effects

An actor's declared effects are three lists of workspace-relative path patterns:

```python
from troupe_plugin_sdk.effects import Effects

effects = Effects(write=("src/**", "docs/*.md"), delete=("build/**",), move=("drafts/**",))
```

In a pattern, `*` matches within one part of a path, `?` matches one character, and `**`, as a whole part, matches
any number of parts: `src/**` matches `src/a.py` and `src/pkg/b.py`, but not `src` itself. `Glob` uses the same
patterns. A malformed pattern raises a `PatternError` naming the effect and the pattern. Its `rule` says what's
wrong without the pattern, for a message that mustn't repeat it.

A pattern can't start with `.git` or `.troupe`, or hold a control character. With nothing declared (`Effects()`), an
actor is read-only. Deleting and moving are declared apart from writing,
because they're more destructive. A call the effects don't allow is an error result naming the tool, the path and
the effect it needs, and nothing changes. The check isn't enforcement: the runner is still a process on the host, so
troupe records the local stage's effects as unenforced.

## A runner's tool loop

```python
from troupe_plugin_sdk.declaration import Declaration
from troupe_plugin_sdk.events import EventNumbering
from troupe_plugin_sdk.tools import Tools

tools = Tools.for_declaration(Declaration.from_run_start(params))  # effects, workspace, scratch
numbering = EventNumbering(run_id, event_max_bytes, next_seq=1)  # after init, seq 0

offered = tools.offered()  # each tool's name, description and input schema, naming scratch
# ... ask the model, offering `offered`; for each tool call in its reply:
step = tools.run(call_id, name, arguments, numbering)
for event in step.events:  # tool_call, then tool_result
    send(event)
reply_to_model(call_id, step.output)
```

`arguments` is the call's input as an object, or as the JSON text of one. An unknown tool, malformed input, a refused
path or effect, and a call that fails are each an error result the model can read and act on. None of them ends the
run. The two events are numbered from the same counter as the runner's other events, and fitted to `eventMaxBytes`.

## The model that answered

```python
from troupe_plugin_sdk.events import ServedModels

served = ServedModels(asked_model)  # the model init named, or None
for body in served.note(reply_model):  # the model the service says answered
    send({"runId": run_id, "seq": numbering.take(), **body})
```

`note` returns nothing for an empty name, the model init named, or a model already noted, and a `served_model` body
the first time another model answers. Send it before the events that report that answer. A name that isn't a
model's shape (1 to 256 characters, no control character) is a `log` warning instead, since a cut name would record
a model that doesn't exist.

## Lost content

When content of the run's conversation is lost and the run carries on, because the engine compacted it or the runner
dropped or summarised part of the conversation it holds, the runner sends a `context` event at that point.
`context_event` builds it, numbered from the same counter as the runner's other events:

```python
from troupe_plugin_sdk.events import EventNumbering, context_event

numbering = EventNumbering(run_id, event_max_bytes, next_seq=1)  # after init, seq 0

event = context_event(
    numbering,
    "compacted",  # or "truncated", or "other" with the message saying what was lost
    "engine",  # or "runner", when the runner reduced the conversation itself
    "The engine summarised the earlier conversation.",
    tokens_before=41000,  # each count is optional: pass only what the engine or runner knows
)
send(event)
```

The message is cut to the summary limit and to `eventMaxBytes`, like a tool event's summaries. A count left as `None`
is left out of the event. A kind or `by` off the contract's list raises a `ProtocolError`, and the counter is left as
it was. A loss that ends the run isn't a `context` event: the run's `result` reports it.

## Compaction

A runner that holds its own conversation and is told `onContextFull` `compact` in `run/start` makes room by replacing
old tool results with a short stub, oldest first, and keeping the call. `troupe_plugin_sdk.compaction` holds the rules,
so every such runner compacts the same way. The runner offers its results in conversation order, replaces the content
of each one `choose` returns with `stub(tool)`, and sends one `context` event with kind `truncated`, by `runner`:

```python
from troupe_plugin_sdk.compaction import Candidate, Estimate, choose, stub

estimate = Estimate()  # bytes to tokens; calibrate() it from each request's reported input tokens
candidates = [
    Candidate(index, tool, size, latest=in_latest_turn)
    for index, tool, size, in_latest_turn in results
]
for index in choose(candidates, estimate_bytes=size_now, target_bytes=size_wanted):
    replace_content(index, stub(tool_at(index)))
```

`choose` never picks a result of the latest turn, which the model hasn't read yet, one already stubbed, or one no
larger than its stub. It stops once the estimate is at or below the target, and returns nothing when nothing can
help: the run then ends with `context-length`. Nothing here calls a model, so a compaction costs no tokens. The
character, the direction and the model's own messages are the runner's to keep: it never offers them.

| Setting | Default | What it sets |
|---|---|---|
| `BYTES_PER_TOKEN` | 3 | The bytes taken to make a token, until the engine reports a count to calibrate from |
| `COMPACT_AT_SHARE` | 0.85 | The share of a known window above which the runner compacts before its next request |
| `COMPACT_TO_SHARE` | 0.5 | The share a compaction brings the conversation down to |

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
