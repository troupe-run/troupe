# Actor runners

An actor runs through a **runner**: a separate process that troupe starts and talks to over its standard input
and output. A runner can be written in any language. This page and the schemas in
[`protocol/schemas/runner/`](../protocol/schemas/runner/) are all you need to write one.

troupe ships one runner so far, the [scripted runner](../plugins/runner-scripted/README.md), which tests use to
produce every outcome on demand. A Claude Code runner and a local-model runner follow (decision
[#16](https://github.com/troupe-run/troupe/issues/16)).

## The contract

### Framing

- Messages are [JSON-RPC 2.0](https://www.jsonrpc.org/specification), one message per line: UTF-8 JSON ended by
  `\n`. JSON escapes line feeds inside strings, so a message never contains a raw one.
- Standard output carries protocol messages and nothing else. Anything else there is a protocol violation, and
  troupe stops the runner.
- Standard error is free-form diagnostics. troupe keeps it with the run.
- A message may be large (well over 64 KiB). troupe accepts lines up to `RUNNER_MAX_MESSAGE_BYTES`.

### Messages

| Method | Direction | Kind | Params | Result |
|---|---|---|---|---|
| `initialize` | troupe → runner | request | `protocolVersions`, `host {name, version}` | `protocolVersion`, `runner {name, version}`, `capabilities` |
| `run/start` | troupe → runner | request | `runId`, `instructions`, `workspace`, `options`, `limits {eventMaxBytes}` | `runId` |
| `run/event` | runner → troupe | notification | one run event | — |
| `run/transcript` | runner → troupe | notification | `runId`, `record`, `encoding` (optional) | — |
| `run/cancel` | troupe → runner | request | `runId` | `{}` |
| `shutdown` | troupe → runner | request | `{}` | `{}` |

A run goes like this:

1. troupe sends `initialize` with the protocol versions it supports (version 1 today). The runner answers with
   the version it chose, its name and version, and `capabilities` (an object of booleans; version 1 requires
   none). If it supports none of the offered versions, it answers with an error whose `details` name the
   versions it does support, and troupe starts no run.
2. troupe sends one `run/start`. The runner answers with the run id, then starts the actor. **A runner process
   serves one run.** A second `run/start` is refused.
3. The runner sends `run/event` notifications as the actor works, and the engine's native output as
   `run/transcript` notifications.
4. When the actor finishes, the runner sends one `result` event. troupe then sends `shutdown`; the runner answers
   and exits.

`run/start` carries everything the runner may use from troupe. `options` holds runner-specific settings, which
troupe passes through without looking inside them. `limits.eventMaxBytes` is the largest serialised event troupe
keeps inline: summarise below it.

### Run events

Every event has `runId`, `seq` and `type`. `seq` starts at 0 and goes up by one with each event: no gaps, no
repeats.

| Type | Fields | Rules |
|---|---|---|
| `init` | `runner {name, version}`, `tools`, `engine {name, version, model}` (optional), `native` (optional) | Always the first event, `seq` 0. |
| `turn` | `role` (`assistant` or `user`), `text`, `native` (optional) | One message turn, summarised. |
| `tool_call` | `callId`, `tool`, `inputSummary`, `native` (optional) | |
| `tool_result` | `callId`, `isError`, `outputSummary`, `outputBytes` | `callId` matches an earlier `tool_call`. The full output belongs in the transcript. |
| `retry` | `attempt`, `maxAttempts` (optional), `delayMs`, `reason`, `message` (optional) | `reason` is `authentication`, `rate-limit`, `network`, `server` or `other`. Send one each time the engine retries. |
| `log` | `level` (`debug`, `info`, `warning`, `error`), `message` | A diagnostic worth keeping with the run. |
| `result` | `status` (`ok` or `error`), `message`, `turns`, `durationMs`, `usage`, `costUsd`, `native` (all but the first two optional) | Exactly one, last, for a run that ends on its own. |
| `oversized` | `originalType`, `bytes`, `ref` | Written by troupe, never by a runner (see [Oversized events](#oversized-events)). |

- **`result.status` is `error` whenever the engine reported an error,** whatever else it reported alongside it.
  Claude Code, for example, reports failures with `"subtype": "success"` and `"is_error": true`; that is an
  `error`.
- **Nothing is required that only one engine has.** Engine-specific detail goes under `native`, or in the
  runner's own `options`. A runner with no model leaves out `engine`.
- **Events are summaries.** Full tool inputs and outputs go in the transcript.

### Oversized events

An event larger than `RUN_EVENT_MAX_BYTES` isn't refused. troupe stores the whole event in the artifact store and
passes on an `oversized` event in its place, with the same `seq`, the original type, its size in bytes and the
stored event's `ref` (`sha256:` and the hex SHA-256 of the event's bytes). The run carries on and nothing is lost.
A runner should still summarise below `limits.eventMaxBytes`, because events are destined for git.

### The transcript

`run/transcript` carries the engine's native output, one record at a time, unchanged and in order. `record` is
the record without its line ending. `encoding` is `utf-8` (the default) or `base64` for bytes that aren't text.
troupe stores the records, each followed by `\n`, as the run's transcript, and never interprets them. For Claude
Code, that reproduces its stream-json output byte for byte.

### Where transcripts are kept

Transcripts can be large, and they hold whatever the actor's tools read, secrets included, so they stay out of
git (decision [#4](https://github.com/troupe-run/troupe/issues/4)). troupe keeps them in an **artifact store**
and records only their reference.

- **References** are `sha256:` followed by the lowercase hex SHA-256 of the artifact's bytes. The same bytes
  always get the same reference, and any copy can be checked against it.
- **Reads are verified.** If a stored file's bytes no longer match its reference, reading fails with
  `artifact.corrupt` instead of returning them. A reference that isn't in the store fails with
  `artifact.missing`.
- **The local store** is a directory: `sha256/<first two hex digits>/<hex>`. It writes its own `.gitignore`
  (containing `*`) the first time it is used, so git ignores it without any change to your own `.gitignore`.
- **Writes are atomic.** An artifact is streamed into `tmp/` and moved into place when finished; until then it
  can't be read. If troupe is killed mid-write, the temporary file stays in `tmp/`; it is never mistaken for an
  artifact, and is safe to delete when no troupe command is running.
- The store is a port: another store (object storage, a hosted store) can replace the local one without changing
  anything that uses it.

### Cancel, end of input and shutdown

- **`run/cancel`** may arrive at any time after `run/start`. Answer it, stop the actor and exit. You may send a
  final `result` with status `error` first; troupe doesn't require one.
- **End of input:** when standard input closes, stop the actor and exit. That is how a runner avoids outliving a
  troupe that has gone away.
- **`shutdown`** follows the `result`. Answer it and exit.

troupe gives a runner `RUNNER_CANCEL_GRACE_SECONDS` to exit after `run/cancel` or `shutdown`, then kills the
runner and every process it started.

### Errors

A JSON-RPC error's `data` is troupe's structured error ([`error.schema.json`](../protocol/schemas/error.schema.json)):
a dotted `code`, the `problem`, the `fix`, and optionally a `path` and `details`. The JSON-RPC `code` is a standard
value (-32700 to -32600), or -32000 when the runner refuses a valid request (such as a second `run/start`).

### Mapping an engine: Claude Code

How Claude Code's stream-json maps onto run events. The Claude Code runner implements this; the scripted runner's
fixtures pin it.

| stream-json record | Run event |
|---|---|
| `system/init` | `init`, with the whole record under `native` |
| `assistant` message | `turn`, plus one `tool_call` per `tool_use` block |
| `user` message with `tool_result` blocks | one `tool_result` per block |
| `system/api_retry` | `retry`: `authentication_failed` → `authentication`, HTTP 429 → `rate-limit`, connection errors → `network`, 5xx → `server` |
| `result` | `result`, with `status` `error` whenever `is_error` is true, whatever `subtype` says |
| every line | one `run/transcript` record, verbatim |
