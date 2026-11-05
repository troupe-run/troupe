# Actor runners

An actor runs through a **runner**: a separate process that troupe starts and talks to over its standard input
and output. A runner can be written in any language. This page and the schemas in
[`protocol/schemas/runner/`](../protocol/schemas/runner/) are all you need to write one.

`troupe perform` runs an actor through a runner and records the run: see [contributing/runs.md](runs.md).

In Python, the [plugin SDK](../packages/troupe-plugin-sdk/README.md) (`troupe_plugin_sdk.runner`) has the contract's
types, checked against those schemas, and core uses the same ones. A runner in another language reads the schemas.

troupe ships three runners: the [scripted runner](../plugins/runner-scripted/README.md), which tests use to produce
every outcome on demand, the [Claude Code runner](../plugins/runner-claude-code/README.md), and the
[Ollama runner](../plugins/runner-ollama/README.md), which drives a local model through Ollama's own API with troupe's
own tool loop (decision [#16](https://github.com/troupe-run/troupe/issues/16)). An OpenAI runner follows
([#162](https://github.com/troupe-run/troupe/issues/162)).

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
| `initialize` | troupe → runner | request | `protocolVersions`, `host {name, version}`, `capabilities` | `protocolVersion`, `runner {name, version}`, `capabilities` |
| `run/start` | troupe → runner | request | `runId`, `direction`, `character` (optional), `workspace`, `effects {write, delete, move}`, `scratch`, `options`, `runtime {name, endpoint, model, credential}` (optional), `limits {eventMaxBytes}` | `runId` |
| `run/event` | runner → troupe | notification | one run event | — |
| `run/transcript` | runner → troupe | notification | `runId`, `record`, `encoding` (optional) | — |
| `run/cancel` | troupe → runner | request | `runId` | `{}` |
| `shutdown` | troupe → runner | request | `{}` | `{}` |

A run goes like this:

1. troupe sends `initialize` with the protocol versions it supports (version 0 today: the draft contract, which changes in place with no
   compatibility promise until troupe commits to version 1) and the capability names
   it supports. The runner answers with one of the offered versions, its name and version, and the capabilities
   it will use, each one from the offer (version 0 defines none, so the offer and the answer are empty lists). A
   version or capability troupe didn't offer is a protocol violation. If the runner supports none of the offered
   versions, it answers with an error whose `details` name the versions it does support, and troupe starts no
   run.
2. troupe sends one `run/start`, with a new run id (a UUID, in canonical lowercase form). The runner answers
   with the same run id, then starts the actor. **A runner process
   serves one run.** A second `run/start` is refused.
3. The runner sends `run/event` notifications as the actor works, and the engine's native output as
   `run/transcript` notifications.
4. When the actor finishes, the runner sends one `result` event. troupe then sends `shutdown`; the runner answers
   and exits.

`run/start` carries everything the runner may use from troupe. `direction` is what the actor is asked to do in this
run, and `character` who the actor is (its standing prompt), left out when it has none: keep them apart, as an
engine's task and system prompt. `options` holds runner-specific settings, which
troupe passes through without looking inside them. The runner publishes their schema (see
[Publishing a runner's schemas](#publishing-a-runners-schemas)), and refuses an option it doesn't define, with an
error naming it, rather than ignoring it. `limits.eventMaxBytes` is the largest serialised event troupe
keeps inline: summarise below it. `effects` and `scratch` are covered in [Applying the effects](#applying-the-effects).
`runtime` is covered in [The runtime and its credential](#the-runtime-and-its-credential).

### The runtime and its credential

A runner that talks to a service, such as a local engine or a hosted API, takes it from the actor's **runtime**:
a service defined once in config (`runtimes.<name>`) and resolved by troupe from its built-in runtimes, the
theatre's config and the person's environment. troupe's runner table says whether a runner takes one (`required`,
`optional` or `none`), and config refuses an actor whose runtime doesn't fit its runner.

`run/start`'s `runtime` holds what troupe resolved: `name`, `endpoint` (the base URL your API lives under; add your
own paths), `model`, and `credential`, a boolean. It's absent when the actor names no runtime.

**The credential's value is never in `run/start`**, which troupe records. When `credential` is `true`, your
environment holds the value as `TROUPE_RUNTIME_CREDENTIAL`; when it's `false`, that variable isn't set. The variable
config names (`runtimes.openai.credential.env`, say `MY_OPENAI_KEY`) never reaches you: every runner reads the same
one. The plugin SDK reads it for you (`troupe_plugin_sdk.credential.runtime_credential(params, os.environ)`), and
refuses a `run/start` and an environment that disagree.

- **Send it only to the runtime's endpoint,** and only as the service expects it (an `Authorization` header, for
  example). Don't follow a redirect with it.
- **Never send it back to troupe:** not in a run event, a transcript record, standard error or an error. troupe
  masks the value as `[credential]` in everything it keeps from a run anyway, but a runner that leaks it is still a
  bug.
- troupe refuses a run before starting you when the credential's variable isn't set, when the value is too short
  to mask safely (under 8 bytes), or when the endpoint is plain `http` to a host that isn't a loopback address.

### Applying the effects

`run/start`'s `effects` is the actor's declaration, always with all three lists: `write`, `delete` and `move`, each a
list of workspace-relative patterns. Empty lists mean the actor is read-only. `scratch` is the absolute path of an
empty directory outside the workspace that troupe made for this run, and removes when it ends: the runner and its
engine may use it for anything, with no effect.

A runner applies the declaration its own way, and says how in its `init` event's `effects`:

- **`checked`:** it checks each change its engine asks for before carrying it out. A runner whose engine returns tool
  calls (a local model, an OpenAI-style API) gives them to the plugin SDK's `Tools`, which does exactly this.
- **`translated`:** it translates the declaration into its engine's own rules, as the Claude Code runner does into
  Claude Code's permission rules.

A runner that can do neither doesn't conform: every actor is at least read-only. The SDK gives every runner the same
view of the declaration, whichever way it goes (`troupe_plugin_sdk.declaration`):

```python
from troupe_plugin_sdk.declaration import Declaration, EffectsTranslation

declaration = Declaration.from_run_start(params)  # the effects, the workspace and scratch
declaration.absolute("write")  # each pattern rooted at the workspace: /c/work/out/** on Windows too
declaration.scratch_absolute()


class MyEngineRules:  # an EffectsTranslation
    mode = "translated"

    def translate(self, declaration: Declaration) -> list[str]: ...
```

Neither way is enforcement. troupe audits every run's changes in its workspace afterwards, whatever the runner did,
and lineage records the local stage's effects as `unenforced`.

### Run events

Every event has `runId`, `seq` and `type`. `seq` starts at 0 and goes up by one with each event: no gaps, no
repeats.

| Type | Fields | Rules |
|---|---|---|
| `init` | `runner {name, version}`, `effects` (`checked` or `translated`), `tools`, `engine {name, version, model}` (optional) | Always the first event, `seq` 0. `effects` says how the runner applies the actor's effects (see [Applying the effects](#applying-the-effects)); troupe accepts an `init` without it only when it reads a run recorded before it existed. |
| `turn` | `role` (`assistant` or `user`), `text` | One message turn, summarised. |
| `tool_call` | `callId`, `tool`, `inputSummary` | |
| `tool_result` | `callId`, `isError`, `outputSummary`, `outputBytes` | `callId` matches an earlier `tool_call`. The full output belongs in the transcript. |
| `retry` | `attempt`, `maxAttempts` (optional), `delayMs`, `reason`, `message` (optional) | `reason` is `authentication`, `rate-limit`, `network`, `server` or `other`. Send one each time the engine retries, or the runner retries a request to its engine itself. |
| `log` | `level` (`debug`, `info`, `warning`, `error`), `message` | A diagnostic worth keeping with the run. |
| `result` | `status` (`ok` or `error`), `message`, `turns`, `durationMs`, `usage {inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens}`, `costUsd` (all but the first two optional, and each `usage` counter too) | Exactly one, last, for a run that ends on its own. |
| `oversized` | `originalType`, `bytes`, `ref` | Written by troupe, never by a runner (see [Oversized events](#oversized-events)). |

- **`result.status` is `error` whenever the engine reported an error,** whatever else it reported alongside it.
  Claude Code, for example, reports failures with `"subtype": "success"` and `"is_error": true`; that is an
  `error`.
- **Nothing is required that only one engine has.** Engine-specific detail goes in the transcript, which keeps
  every native record, or in the runner's own `options`. A run event carries no field the contract doesn't
  define. A runner with no model leaves out `engine`.
- **Events are summaries.** Full tool inputs and outputs go in the transcript.

### Oversized events

An event larger than `RUN_EVENT_MAX_BYTES` isn't refused. troupe stores the whole event in the artifact store and
passes on an `oversized` event in its place, with the same `seq`, the original type, its size in bytes and the
stored event's `ref` (`sha256:` and the hex SHA-256 of the event's bytes). The run carries on and nothing is lost.
A runner should still summarise below `limits.eventMaxBytes`, because events are destined for git.

### The transcript

`run/transcript` carries the engine's native output, one record at a time, unchanged and in order. A runner that
holds the conversation itself (one that runs the tool loop, as the Ollama runner does) also sends each message it
adds to the conversation, verbatim as it sent it, before the engine's output that follows it, and sends re-sent
history only once: otherwise the tool outputs it sends back, which the contract says belong in the transcript, would
be missing, and a transcript would grow with the square of its run. `record` is
the record without its line ending. `encoding` is `utf-8` (the default) or `base64` for bytes that aren't text.
troupe stores the records, each followed by `\n`, as the run's transcript, and never interprets them, apart from
masking a runtime's credential. For Claude
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
- **The local store** is a directory: `sha256/<first two hex digits>/<hex>`. troupe keeps it at
  `.troupe/local/artifacts/` in the theatre, and `.troupe/local/` is kept out of git. The store also writes its own
  `.gitignore` (containing `*`) the first time it is used, as a guard: wherever its directory is, git ignores it,
  and your own `.gitignore` is never changed.
- **Writes are atomic.** An artifact is streamed into `tmp/` and moved into place when finished; until then it
  can't be read. If troupe is killed mid-write, the temporary file stays in `tmp/`; it is never mistaken for an
  artifact, and is safe to delete when no troupe command is running.
- **Stores are found by name.** The store is a port (`ArtifactStore` in `troupe.core.artifacts`). Each store is its
  own package, registered in the `troupe.artifacts` entry point group; the local one is `troupe-artifacts-local`,
  registered as `local`. troupe never imports a store package, so another store (object storage, a hosted store)
  can replace the local one without changing anything that uses it. Asking for a store that isn't installed fails
  with `artifact.unknown-store`, naming the stores that are.

### Environment

A runner starts with only the environment variables troupe's caller names for it, plus the minimum the operating
system needs (`SYSTEMROOT` on Windows). Nothing is passed through from troupe's own environment: the runner policy,
`RUNNER_ENVIRONMENT`, selects nothing. A runner that needs a credential or a setting is given it explicitly. A
runtime's credential arrives as `TROUPE_RUNTIME_CREDENTIAL` ([The runtime and its
credential](#the-runtime-and-its-credential)).

### Cancel, end of input and shutdown

- **`run/cancel`** may arrive at any time after `run/start`. Answer it, stop the actor and exit. You may send a
  final `result` with status `error` first; troupe doesn't require one.
- **End of input:** when standard input closes, stop the actor and exit. That is how a runner avoids outliving a
  troupe that has gone away.
- **`shutdown`** follows the `result`. Answer it and exit.

troupe gives a runner `RUNNER_CANCEL_GRACE_SECONDS` to exit after `run/cancel` or `shutdown`, then kills the
runner and every process it started.

### Errors

A JSON-RPC error's `data` is troupe's structured error shape
([`error.schema.json`](../protocol/schemas/error.schema.json)): a dotted `code`, the `problem`, the `fix`, and
optionally a `path` and `details`. The JSON-RPC `code` is a standard value (-32700 to -32600), or -32000 when the
runner refuses a valid request (such as a second `run/start`).

The contract defines these codes ([`runner/errors.schema.json`](../protocol/schemas/runner/errors.schema.json)).
Only `runner.unsupported-version` and `runner.requirement-unmet` carry `details`:

| Code | JSON-RPC code | When |
|---|---|---|
| `runner.parse-error` | -32700 | The request isn't JSON |
| `runner.invalid-request` | -32600 | The message isn't a JSON-RPC 2.0 request |
| `runner.not-initialized` | -32600 | A request other than `initialize` came first |
| `runner.unknown-method` | -32601 | The method isn't one the runner serves |
| `runner.unsupported-version` | -32000 | None of the offered versions is supported; `details.supportedVersions` names the ones that are |
| `runner.already-started` | -32000 | A second `run/start` |
| `runner.invalid-params` | -32602 | The params aren't the ones the contract defines |
| `runner.requirement-unmet` | -32000 | What the runner runs on doesn't meet one of its requirements, such as its engine's least version, so it refuses `run/start`. `details` name the `requirement`, what's `wanted` (such as `>= 0.12.6`) and what was `found`, left out when it found nothing. How components declare requirements in general is Decision [#281](https://github.com/troupe-run/troupe/issues/281) |

Any other code is the runner's own, and the runner publishes it (next section).

### Publishing a runner's schemas

Every schema troupe ships is strict: each object closed, each value typed. A runner publishes two JSON Schemas
(draft 2020-12), held to the same rule, in a `schemas/` directory beside its code and installed with it, so troupe
can check an actor's options without starting the runner (for a Python runner, inside its package, as the scripted
runner does):

- **`options.schema.json`**, for its `run/start` options. A runner with no options publishes one that accepts only
  `{}`.
- **`errors.schema.json`**, for its own error codes and each code's `details`. It refers to the shared error fields
  (`error.schema.json#/$defs/fields`), closes the object with `unevaluatedProperties: false`, and lists one `oneOf`
  branch per code.

The contract leaves room for them with two extension points: `options` in `run/start` is
`{"$dynamicRef": "#runnerOptions"}`, and a runner error's `data` is the contract's codes or
`{"$dynamicRef": "#runnerErrors"}`. On their own they accept only `{}` options and only the contract's codes. To
validate a runner's messages, bind its schemas in a schema that sets each `$dynamicAnchor` and refers to the
contract:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/my-runner/bound.schema.json",
  "$ref": "https://troupe.run/protocol/runner/message.schema.json",
  "$defs": {
    "options": {"$dynamicAnchor": "runnerOptions", "$ref": "https://example.com/my-runner/options.schema.json"},
    "errors": {"$dynamicAnchor": "runnerErrors", "$ref": "https://example.com/my-runner/errors.schema.json"}
  }
}
```

The [scripted runner's schemas](../plugins/runner-scripted/schemas/) are a worked example. troupe doesn't load a
runner's schemas at run time yet; how it will is decided with config ([#60](https://github.com/troupe-run/troupe/issues/60)).

### Mapping an engine: Claude Code

How Claude Code's stream-json maps onto run events. The
[Claude Code runner](../plugins/runner-claude-code/README.md) implements this, and its fixtures pin it: real Claude Code
output, each line paired with the events it maps to.

| stream-json record | Run event |
|---|---|
| `system/init` | `init`, with the engine's name, version and model; the whole record stays in the transcript |
| `assistant` message | A `turn` for its text, if it has any, then one `tool_call` per `tool_use` block. An API failure arrives this way too, as an `assistant` message with `error` set and the error's text as its content |
| `rate_limit_event` | None while its status is `allowed` (the transcript keeps it); otherwise a `log` warning naming the status |
| `user` message with `tool_result` blocks | one `tool_result` per block. A block whose call was never reported is a `log` warning instead, since a `tool_result` needs its `tool_call` |
| `system/api_retry` | `retry`: `authentication_failed` → `authentication`, HTTP 429 → `rate-limit`, 5xx → `server`, no HTTP status (a connection error, which Claude Code reports as `"error": "unknown"`) → `network`, anything else → `other` |
| `result` | `result`, with `status` `error` whenever `is_error` is true, whatever `subtype` says. Its `usage` maps `input_tokens`, `output_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens` onto `inputTokens`, `outputTokens`, `cacheReadTokens` and `cacheWriteTokens`. Each tool in `permission_denials` is a `log` warning just before it |
| a record type or `system` subtype not named here | a `log` at `debug` the first time it appears in the run, so a format change shows without failing the run |
| a line that isn't a JSON object | a `log` warning |
| every line | one `run/transcript` record, verbatim (`base64` if it isn't UTF-8), before any event it maps to |

`init` comes first even when Claude Code writes something else first (2.1.302 writes `system/ui_invalidate` before
its init): a `log` about an earlier record waits for `init`. Summaries (`turn` text, `inputSummary`,
`outputSummary`, and log, retry and result messages) are cut on a character boundary to fit within
`limits.eventMaxBytes`, ending with how many bytes were left out.

### Mapping an engine: Ollama

The [Ollama runner](../plugins/runner-ollama/README.md) is the other shape: the engine only answers, and the runner
holds the conversation and runs the tools. It drives Ollama's own `/api/chat`, carries out each tool call with the
plugin SDK's `Tools` (so `init`'s `effects` is `checked`), and maps the exchange like this. Its fixtures pin it: real
Ollama answers, with what the runner sent for each.

| From Ollama | Run event |
|---|---|
| `/api/version`, and the options' model | `init`, with the engine's name, version and model |
| an answer's text, once its `done` line has come | a `turn`, if it has any text |
| an answer's `thinking` | none; the transcript keeps it |
| each `tool_calls` entry | `tool_call` and `tool_result`, from the SDK. A call with no id gets `call-<request>-<position>` |
| a request made again: a connection that failed, dropped or went silent, or status 500, 502, 503 or 504 | `retry`: `network` for the connection, `server` for the status |
| `done_reason` `length` | `log` warning |
| an answer with no tool call | `result` `ok`, with its text |
| any other status, an `error` line, `maxTurns` reached, or retries spent | `result` `error`, with Ollama's message |
| each answer's `prompt_eval_count` and `eval_count` | summed into `result.usage`'s `inputTokens` and `outputTokens` |

Its transcript is the first request's body, then before each later request the messages the runner added (the
answer and its `tool` messages), each encoded exactly as inside that request, and every line of every answer: each
record verbatim and once. Every request asks Ollama to refuse a conversation longer than the window rather than cut
it (`truncate` and `shift` `false`), which Ollama 0.12.6 added, so the runner requires it and refuses an older one with
`runner.requirement-unmet`.

## How troupe runs a runner

`troupe.core.runners.host.run_actor` starts the runner, performs the handshake, starts the run and supervises it.
The caller gives it the runner's command, the run (a UUID run id, the direction, the workspace, the runner's
options and the character), an artifact store, an effect check, and optionally the limits, an `on_event` callback, an `on_announce`
callback and a cancel signal.

- **Events reach the caller as they arrive,** in `seq` order. `on_event` is awaited before the next message is read,
  so a slow consumer slows the runner down rather than troupe buffering without limit.
- **Every message is checked.** Anything the contract doesn't allow ends the run as `crashed` with
  `runner.protocol`, naming what was wrong and on which line of the runner's output: a line that isn't JSON or
  JSON-RPC, a duplicated JSON key, `NaN` or `Infinity`, a method the contract doesn't define, an answer to a
  request troupe never sent, a version or capability troupe didn't offer, another run's id, an event out of
  sequence, before `init` or after `result`, a `tool_result` with no earlier `tool_call`, a `base64` record that
  isn't base64, or a message over `RUNNER_MAX_MESSAGE_BYTES`. troupe never reads such a message with a guess.
- **Cancelling** sends `run/cancel` and gives the runner `RUNNER_CANCEL_GRACE_SECONDS` to exit, then kills it and
  every process it started. The same happens after `shutdown`.
- **Notices** tell the caller what is happening without waiting silently. They have the shape of
  [`notice.schema.json`](../protocol/schemas/notice.schema.json): `run.silent` when no event has arrived for
  `RUN_SILENCE_ANNOUNCE_SECONDS`, and `run.retrying` for each `retry` event. A `retry` with reason
  `authentication` stops the run at once (`RUNNER_FAIL_FAST_ON_AUTH_RETRY`): a bad credential otherwise looks like
  a hang for minutes.
- **Standard error** is kept in the artifact store too, up to `RUNNER_STDERR_MAX_BYTES`: its first and last halves,
  with a marker saying how much was left out between them.

### Outcomes

Every run attempt ends with exactly one outcome, returned as data with an error (in the protocol's error shape)
for every outcome but `succeeded` and `cancelled`. The first row that matches wins.

| Outcome | When | Error code |
|---|---|---|
| `could-not-start` | The runner couldn't be started, or refused or timed out the handshake or `run/start` | `runner.start-failed`, `runner.incompatible`, `runner.start-timeout` |
| `crashed` | The runner broke the contract | `runner.protocol` |
| `failed` | The run was stopped because authentication failed | `run.authentication` |
| `failed` | The transcript passed `RUN_TRANSCRIPT_MAX_BYTES` | `run.transcript-too-large` |
| `failed` | The `result` had status `error` | `run.error-result` |
| `failed` | The `result` was `ok`, but the effect check failed: an expected file wasn't made or changed, the run changed a file its actor's effects don't declare, or both | `run.effect-missing`, `effects.outside-declared`, `effects.check-failed` |
| `failed` | The `result` was `ok` and the effect check passed, but the runner exited non-zero or had to be killed: the run's state is uncertain | `run.unclean-exit` |
| `succeeded` | The `result` was `ok`, the effect check passed, and the runner exited with code 0 | — |
| `timed-out` | No `result` by `RUN_TIMEOUT_SECONDS` | `run.timeout` |
| `cancelled` | No `result`, and the caller cancelled the run | — |
| `crashed` | No `result`, for any other reason | `runner.crashed` |

Success takes all three signals together. The exit code alone never makes a run succeed: a runner that exits 0
without a `result` has `crashed`. The outcome also records the exit code, whether the runner exited or was
killed, the transcript's and standard error's references, and the limits in effect.

**`ending`** is `killed` only when troupe's kill is what ended the runner, and then the exit code says nothing about
the run. A runner that exits by itself is `exited`, with its own exit code, even if troupe had decided to kill it or
had already sent the kill. troupe decides this from the exit status once the process has ended, so the timing of
the kill doesn't change it (see [Child processes](platform.md#child-processes)). For example, a runner that sends
an event after its `result` has broken the contract and crashes the run. If it has already answered `shutdown` by
exiting 0, its ending is `exited` with code 0.

**The effect check** has no default, so a caller can't forget it. `ExpectedFiles(paths)` needs each file to exist
after the run and to differ from before it; `NoEffectExpected` is for a run with nothing to check.

## Limits

Every limit has its default in `troupe.core.defaults`, and each can be overridden per run (`RunLimits`).

| Setting | Default | What it limits |
|---|---|---|
| `RUNNER_START_TIMEOUT_SECONDS` | 30 | Starting the runner and answering `initialize` |
| `RUN_TIMEOUT_SECONDS` | 3600 | The whole run; past it, the run is cancelled and ends `timed-out` |
| `RUNNER_CANCEL_GRACE_SECONDS` | 10 | How long a runner has to exit after `run/cancel` or `shutdown` before it and its children are killed |
| `RUN_SILENCE_ANNOUNCE_SECONDS` | 30 | How long a run may go without an event before troupe says so |
| `RUNNER_MAX_MESSAGE_BYTES` | 67108864 | One protocol message (64 MiB) |
| `RUN_EVENT_MAX_BYTES` | 65536 | One run event kept inline (64 KiB); larger ones are stored and referenced |
| `RUN_TRANSCRIPT_MAX_BYTES` | 1073741824 | One run's transcript (1 GiB); past it, the run is cancelled and ends `failed` |
| `RUNNER_STDERR_MAX_BYTES` | 1048576 | The runner's standard error kept (1 MiB): its first and last halves, with a marker between |
| `RUNNER_FAIL_FAST_ON_AUTH_RETRY` | true | Whether a `retry` with reason `authentication` cancels the run at once |

## Checking a runner

troupe's conformance suite checks a runner against this contract: the handshake, refusing a protocol version it
doesn't support, refusing a second `run/start`, refusing an option it doesn't define (the suite adds
`troupeConformanceUnknownOption`), acknowledging `run/cancel` and exiting, exiting when its input
closes, and a whole run (`init` first, gap-free `seq`, one `result`, then `shutdown`). Each check starts the runner
afresh. Give it the runner's command line as a JSON array, and the `run/start` options for a short run that
succeeds:

```console
TROUPE_CONFORMANCE_RUNNER='["python", "-m", "troupe_runner_scripted"]' \
TROUPE_CONFORMANCE_OPTIONS='{"script": {"steps": [{"event": {"type": "init", "runner": {"name": "scripted", "version": "0"}, "tools": []}}, {"event": {"type": "result", "status": "ok", "message": "done"}}]}}' \
uv run pytest packages/troupe/tests/test_runner_conformance.py -k environment
```

The same checks are available to code as `troupe.core.runners.conformance.check_runner`.
