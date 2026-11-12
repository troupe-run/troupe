# Actor runners

An actor runs through a **runner**: a separate process that troupe starts and talks to over its standard input
and output. A runner can be written in any language. This page and the schemas in
[`protocol/schemas/runner/`](../protocol/schemas/runner/) are all you need to write one.

`troupe perform` runs an actor through a runner and records the run: see [contributing/runs.md](runs.md).

In Python, the [plugin SDK](../packages/troupe-plugin-sdk/README.md) (`troupe_plugin_sdk.runner`) has the contract's
types, checked against those schemas, and core uses the same ones. A runner in another language reads the schemas.

troupe ships four runners: the [scripted runner](../plugins/runner-scripted/README.md), which tests use to produce
every outcome on demand, the [Claude Code runner](../plugins/runner-claude-code/README.md), the
[Ollama runner](../plugins/runner-ollama/README.md), which drives a local model through Ollama's own API with troupe's
own tool loop (decision [#16](https://github.com/troupe-run/troupe/issues/16)), and the
[OpenAI runner](../plugins/runner-openai/README.md), which drives OpenAI's Responses API with the same kind of loop
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
| `run/start` | troupe → runner | request | `runId`, `direction`, `character` (optional), `workspace`, `effects {write, delete, move}`, `scratch`, `options`, `runtime {name, endpoint, model, credential, price}` (optional, and `price` within it), `limits {eventMaxBytes}` | `runId` |
| `run/event` | runner → troupe | notification | one run event | — |
| `run/transcript` | runner → troupe | notification | `runId`, `record`, `encoding` (optional), `kind` (exactly when the runner accepted `transcript-kinds`) | — |
| `run/cancel` | troupe → runner | request | `runId` | `{}` |
| `shutdown` | troupe → runner | request | `{}` | `{}` |

A run goes like this:

1. troupe sends `initialize` with the protocol versions it supports (version 0 today: the draft contract, which changes in place with no
   compatibility promise until troupe commits to version 1) and the capability names
   it supports. The runner answers with one of the offered versions, its name and version, and the capabilities
   it will use, each one from the offer. The contract defines one capability, `transcript-kinds` (see
   [Record kinds](#record-kinds)), and troupe offers it. In the runner's answer, a capability the contract doesn't
   define, or one troupe didn't offer, is a protocol violation. Capability names are a closed list in the schemas,
   so a new capability is a change to the contract, released as a protocol release, like any other. If the runner supports none of the offered
   versions, it answers with an error whose `details` name the versions it does support, and troupe starts no
   run.
2. troupe sends one `run/start`, with a new run id (a UUID, in canonical lowercase form). The runner answers
   with the same run id, then starts the actor. **A runner process
   serves one run.** A second `run/start` is refused.
3. The runner sends `run/event` notifications as the actor works, and its transcript records as
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

**What runtime fits**, in the table's `fit` (`troupe.core.interim.RuntimeFit`), is judged from the runtime's fields
alone, so troupe refuses a pair your runner would refuse before anything is recorded: in config, and at perform with
`runtime.unfit` once the person's environment is applied.

- `credential`: whether you send a runtime's credential. `False` refuses a runtime that has one.
- `path`: what the endpoint's path must be: `"none"` (you add your own API's path, as the Ollama runner does),
  `"required"` (your requests go below it, such as `/v1`, as the OpenAI runner's do) or `"any"`. A single trailing
  `/` is no path; `//` is one.

Your runner should refuse the same runtimes itself, since a host other than troupe may start it.
`packages/troupe/tests/test_runtime_fit.py` holds the table to each runner that needs a runtime: add yours to its
`ORACLES`.

`run/start`'s `runtime` holds what troupe resolved: `name`, `endpoint` (the base URL your API lives under; add your
own paths), `model`, `credential`, a boolean, and `price` when the theatre prices the run's model. It's absent when
the actor names no runtime.

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

### Cost: reported or estimated

`result` has two cost fields, and a result carries at most one of them:

- **`costUsd` is what the engine or its service reported,** summed over the run. Never put a number you worked out in
  it.
- **`estimatedCostUsd` is an estimate,** and only from troupe's price: `run/start`'s `runtime.price`, in US dollars per
  million tokens (`input` and `output`, and optionally `cacheRead` and `cacheWrite`). Send it only when nothing
  reported a cost and `run/start` carried a price, and never estimate from a price list of your own. troupe drops an
  estimate from a run it gave no price, records the result without it, and warns with `run.estimate-dropped`.
- **An estimate prices every token or is absent.** Leave it out when `usage` has no `inputTokens` or `outputTokens`,
  when the price has a rate for a counter your engine didn't report, or when a counter holds tokens the price has no
  rate for. Never price one kind of token at another's rate. `inputTokens` leaves out cache reads and writes (see
  [What usage counts](#what-usage-counts)), so each token is priced once.

The plugin SDK does the arithmetic and applies those rules: `troupe_plugin_sdk.cost.estimate(usage, price)` returns
the estimate, rounded to ten decimal places, or `None`. Use it rather than your own.

### Run events

Every event has `runId`, `seq` and `type`. `seq` starts at 0 and goes up by one with each event: no gaps, no
repeats.

| Type | Fields | Rules |
|---|---|---|
| `init` | `runner {name, version}`, `effects` (`checked` or `translated`), `tools`, `engine {name, version, model}` (optional) | Always the first event, `seq` 0. `effects` says how the runner applies the actor's effects (see [Applying the effects](#applying-the-effects)). An `init` without it is a protocol violation. |
| `turn` | `role` (`assistant` or `user`), `text` | One message turn, summarised. |
| `tool_call` | `callId`, `tool`, `inputSummary` | |
| `tool_result` | `callId`, `isError`, `outputSummary`, `outputBytes` | `callId` matches an earlier `tool_call`. The full output belongs in the transcript. |
| `retry` | `attempt`, `maxAttempts` (optional), `delayMs`, `reason`, `message` (optional) | `reason` is `authentication`, `rate-limit`, `network`, `server` or `other`. Send one each time the engine retries, or the runner retries a request to its engine itself. |
| `context` | `kind`, `by`, `message`, `tokensBefore`, `tokensAfter`, `messagesBefore`, `messagesAfter` (the four counts optional) | `kind` is `compacted`, `truncated` or `other`, and `by` is `engine` or `runner`. Send one each time content of the conversation is lost and the run carries on (see [Lost content](#lost-content)). |
| `log` | `level` (`debug`, `info`, `warning`, `error`), `message` | A diagnostic worth keeping with the run. |
| `served_model` | `model` | A model other than the one `init` named answered part of the run, as the engine or service named it. Send it the first time each such model answers, before any event reporting that answer; never for `init`'s model, and never twice for one model (troupe treats either as a protocol violation). With no model on `init`, every model that answers is sent once. `model` has a model's shape (1 to 256 characters, no control character); a name outside it is a `log` warning instead. The plugin SDK's `ServedModels` decides. |
| `result` | `status` (`ok` or `error`), `message`, `reason`, `notRetried`, `turns`, `durationMs`, `usage {inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens}`, `costUsd` or `estimatedCostUsd` (all but `status` and `message` optional, and each `usage` counter too) | Exactly one, last, for a run that ends on its own. `reason` is present exactly when `status` is `error` (see [Why a run failed](#why-a-run-failed)), and `notRetried` only beside a reason a `retry` can name (see [When a retry isn't safe](#when-a-retry-isnt-safe)). See [What usage counts](#what-usage-counts). At most one of the two costs (see [Cost: reported or estimated](#cost-reported-or-estimated)). |
| `oversized` | `originalType`, `bytes`, `ref` | Written by troupe, never by a runner (see [Oversized events](#oversized-events)). |

- **`result.status` is `error` whenever the engine reported an error,** whatever else it reported alongside it.
  Claude Code, for example, reports failures with `"subtype": "success"` and `"is_error": true`; that is an
  `error`.
- **Nothing is required that only one engine has.** Engine-specific detail goes in the transcript, which keeps
  every native record, or in the runner's own `options`. A run event carries no field the contract doesn't
  define. A runner with no model leaves out `engine`.
- **Events are summaries.** Full tool inputs and outputs go in the transcript.

### What usage counts

`inputTokens`, `cacheReadTokens` and `cacheWriteTokens` add up to the run's whole input. `inputTokens` is the input
not counted in either cache counter, whatever the engine calls its own input count:

- **An engine whose input count leaves the cache out**, as Anthropic's `input_tokens` does: report it as
  `inputTokens` unchanged. 6 input tokens beside 42158 read from the cache and 5737 written to it is `inputTokens` 6,
  `cacheReadTokens` 42158 and `cacheWriteTokens` 5737.
- **An engine whose input count includes the cache**, as OpenAI's `input_tokens` does: subtract the cache's reads and
  writes. 300 input tokens, 100 read from the cache and 50 written to it, is `inputTokens` 150, `cacheReadTokens` 100
  and `cacheWriteTokens` 50.

Leave a cache counter out when you can't report it, and never estimate one: an absent counter means it wasn't
reported, not that it was 0. Input your engine counted that you can't separate into a cache counter stays in
`inputTokens`. When a run sums several requests, report a cache counter only if every request reported it; for
example, if only some report cache writes, subtract none and leave `cacheWriteTokens` out.

### Why a run failed

A `result` with status `error` says why in `reason`, from this closed list, so troupe can act on a failure the same
way whichever runner reported it. An `ok` result has no `reason`. The rule is the same wherever a result appears:
what a runner sends, what troupe records, and what it reads back. A result that breaks it is a protocol violation.

| Reason | When |
|---|---|
| `authentication` | the engine or service refused the credential |
| `quota` | the account is out of quota, credit or billing |
| `rate-limit` | rate limited past what the runner will wait or retry |
| `network` | the engine couldn't be reached |
| `server` | the engine or service kept failing on its side |
| `configuration` | the endpoint or model can't serve the run: nothing there, a redirect, no such model |
| `context-length` | the conversation outgrew the model's context |
| `output-limit` | an answer was cut at the output limit, and the runner ended the run for it |
| `refused` | the model refused, or the service's content filter stopped it |
| `turn-limit` | the runner's or engine's turn limit was reached |
| `budget` | the runner's or engine's token or cost budget was spent |
| `cancelled` | the run was cancelled and the runner still sent a result |
| `engine` | the engine failed in a way of its own, or sent what the runner can't act on |
| `runner` | the runner itself failed unexpectedly |
| `other` | none of these; the message says what happened |

- **Choose the reason from the engine's structured fields** (a status, an error code, a subtype). Where the engine
  gives none, match the fixed words it documents for that failure, as the Ollama runner does for a 400 over the
  context window, and never guess from free text.
- **A failure the list has no entry for is `other`.** A runner can't add reasons of its own: the list has no
  extension point. A runner that keeps meeting such a failure asks for a reason to be added, as a contract change.
- **Retries that run out end with the last retry's reason.** The five reasons a `retry` can name mean the same on
  both, so a run whose last retry was `rate-limit` ends `rate-limit`.
- **The message still says what happened,** in the engine's or the runner's words: the reason is what to act on,
  the message is what to read.

### When a retry isn't safe

A runner that ends a run on a failure it would otherwise have retried, because retrying could repeat something the
run already did, says so in the `result`'s `notRetried`, so troupe can tell it from retries that ran out. The list is
closed, with one value:

| `notRetried` | When |
|---|---|
| `side-effect` | a tool call had already been carried out or answered, and a retry could carry it out again |

- **Only on an `error` result whose `reason` a `retry` can name:** `authentication`, `rate-limit`, `network`,
  `server` or `other`. On an `ok` result, or beside any other reason, it's a protocol violation, wherever the result
  appears.
- **Absent means the runner retried until its attempts ran out, or doesn't retry that failure.** Send it only when
  you held back.
- **Which runners need it:** one whose retry starts the run's conversation again from the direction, so the tool
  calls already carried out would be asked for and carried out again. The LM Studio runner is one: the library's
  `act()` starts again from the direction. A runner whose retry sends one request again, and carries out a reply's
  calls only once the whole reply has arrived, never needs it: the Ollama, Responses API and Claude Code runners all
  work that way, since the conversation each retry sends already holds every tool result.
- **troupe's outcome carries it,** and its fix says to review the run's changes before performing the actor again
  (see [Outcomes](#outcomes)).

### Lost content

An engine never loses content without the run saying so ([#279](https://github.com/troupe-run/troupe/issues/279)).
When the loss ends the run, the `result` says so, with the reason `context-length` (see
[Why a run failed](#why-a-run-failed)). When content of the conversation is lost and the run carries on, send a
`context` event at that point, before any event that follows from the reduced conversation. A `context` event never
ends the run, and troupe records it with the run's other events.

- **`kind`** says what happened: `compacted` when earlier content was replaced by a summary of it, `truncated` when it
  was dropped outright, or `other` for a loss neither names. A runner can't add kinds of its own. Use `other` and say
  in `message` what was lost, and if you keep meeting the same loss, file an issue to add a kind for it.
- **`by`** says who did it: `engine` when the engine reduced its conversation on its own (Claude Code compacting),
  or `runner` when the runner reduced the conversation it holds and sends to its engine.
- **The counts** are the conversation's tokens and messages before and after the loss. Send each one only when the
  engine or runner knows it, and leave it out otherwise. Claude Code, for example, reports only the tokens before.
- **`message`** says what happened, in words.
- A cut answer at the engine's output limit isn't a `context` event. It ends the run with `output-limit`.

The SDK builds the event with `context_event` from `troupe_plugin_sdk.events`. It numbers the event with the run's
`EventNumbering`, cuts the message to the run's limits, and leaves out each count you pass as `None`:

```python
from troupe_plugin_sdk.events import EventNumbering, context_event

numbering = EventNumbering(run_id, event_max_bytes, next_seq=1)  # after init, seq 0
event = context_event(
    numbering, "compacted", "engine", "Claude Code compacted", tokens_before=41000
)
```

### Oversized events

An event larger than `RUN_EVENT_MAX_BYTES` isn't refused. troupe stores the whole event in the artifact store and
passes on an `oversized` event in its place, with the same `seq`, the original type, its size in bytes and the
stored event's `ref` (`sha256:` and the hex SHA-256 of the event's bytes). The run carries on and nothing is lost,
except an estimate troupe gave no price for: troupe drops that from a `result` first, so the stored event is the
result without it (see [Cost: reported or estimated](#cost-reported-or-estimated)).
A runner should still summarise below `limits.eventMaxBytes`, because events are destined for git.

### The transcript

`run/transcript` carries the run's transcript, one record at a time, in order. Without a kind, a record is the
engine's native output, unchanged, or, from a runner that wasn't offered `transcript-kinds`, one of the records it
would otherwise have labelled. A runner that
holds the conversation itself (one that runs the tool loop, as the Ollama runner does) also sends each message it
adds to the conversation, verbatim as it sent it, before the engine's output that follows it, and sends re-sent
history only once: otherwise the tool outputs it sends back, which the contract says belong in the transcript, would
be missing, and a transcript would grow with the square of its run. `record` is
the record without its line ending. `encoding` is `utf-8` (the default) or `base64` for bytes that aren't text.
troupe never interprets the records, apart from masking a runtime's credential. In a run without kinds it stores
each record followed by `\n`, as the run's transcript: for Claude Code, that reproduces its stream-json output byte
for byte. A run with kinds is stored framed, as [Record kinds](#record-kinds) says.

#### Record kinds

A runner that drives an API has no native output: it conducts an exchange, and what it sends matters as much as
what comes back. Rather than invent a framing for its records, it accepts the `transcript-kinds` capability at
`initialize`, and gives every record a `kind`:

| Kind | The record is |
|---|---|
| `sent` | What the runner sent its engine, verbatim: a request body, or a message it added to the conversation. |
| `received` | What the engine sent back, verbatim: a stream line, a body. |
| `note` | The runner's own record about the exchange, in its own form, such as a response's status and the headers it keeps, or a stream it gave up on. |

It's all or nothing for the run: a runner that accepted the capability gives every record a kind, and one that
didn't gives none. A record that breaks this is a protocol violation, and isn't stored. Offered no capability (a
troupe from before it), send the same records without a kind. A runner that passes on an engine's native output,
such as Claude Code's, has nothing to label and doesn't accept it.

In a run that uses kinds, troupe stores each line as compact JSON: `{"kind": ..., "record": ...}`, with
`"encoding": "base64"` when the runner sent the record as base64
([`transcript-record.schema.json`](../protocol/schemas/transcript-record.schema.json)). It masks the credential in
the record's bytes before it frames them. The transcript limit counts the stored bytes, framing included. The run's
end records `transcriptFormat`, `native` or `kinds`, beside the transcript's reference, so a reader always knows
which form its lines are. The OpenAI and Ollama runners use kinds.

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
  final `result` with status `error` and reason `cancelled` first; troupe doesn't require one.
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
| `assistant` message | A `served_model` first when its `message.model` isn't `system/init`'s, hasn't been sent and isn't `<synthetic>` (Claude Code's mark on a message it made itself); then a `turn` for its text, if it has any, then one `tool_call` per `tool_use` block. A subagent's messages map the same way. An API failure arrives this way too, as an `assistant` message with `error` set and the error's text as its content |
| `rate_limit_event` | None while its status is `allowed` (the transcript keeps it); otherwise a `log` warning naming the status |
| `user` message with `tool_result` blocks | one `tool_result` per block. A block whose call was never reported is a `log` warning instead, since a `tool_result` needs its `tool_call` |
| `system/api_retry` | `retry`: `authentication_failed` → `authentication`, HTTP 429 → `rate-limit`, 5xx → `server`, no HTTP status (a connection error, which Claude Code reports as `"error": "unknown"`) → `network`, anything else → `other` |
| `result` | `result`, with `status` `error` whenever `is_error` is true, whatever `subtype` says. An `error` result's `reason` comes from Claude Code's fields, never its text: a failed `subtype` by name (`error_max_turns` → `turn-limit`, `error_max_budget_usd` → `budget`, `error_during_execution` → `engine`, any other → `other`); for an API error, the last `assistant` record's `error` code when it names its cause (`authentication_failed`, `billing_error` → `quota`, `rate_limit`, `max_output_tokens` → `output-limit`), else the last `retry`'s reason (Claude Code calls a refused connection `server_error`), else `api_error_status` as for a retry; else `other`. An `assistant` record without an error clears both the error code and the retry before it: that call succeeded, so neither explains a later failure. Its `usage` maps `input_tokens`, `output_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens` onto `inputTokens`, `outputTokens`, `cacheReadTokens` and `cacheWriteTokens`; Anthropic's `input_tokens` already leaves out cache reads and writes, so it maps unchanged (see [What usage counts](#what-usage-counts)). Just before the `result`, each model in `modelUsage` not yet sent (and not `system/init`'s or `<synthetic>`) is a `served_model`, then each tool in `permission_denials` is a `log` warning |
| a record type or `system` subtype not named here | a `log` at `debug` the first time it appears in the run, so a format change shows without failing the run |
| a line that isn't a JSON object | a `log` warning |
| every line | one `run/transcript` record, verbatim (`base64` if it isn't UTF-8), before any event it maps to |

`init` comes first even when Claude Code writes something else first (2.1.302 writes `system/ui_invalidate` before
its init): a `log` about an earlier record waits for `init`. Summaries (`turn` text, `inputSummary`,
`outputSummary`, and log, retry and result messages) are cut on a character boundary to fit within
`limits.eventMaxBytes`, ending with how many bytes were left out.

### Mapping an engine: Ollama

The [Ollama runner](../plugins/runner-ollama/README.md) is the other shape: the engine only answers, and the runner
holds the conversation and runs the tools. Its endpoint and model come from the actor's runtime, as the OpenAI runner's
do. It drives Ollama's own `/api/chat`, carries out each tool call with the plugin SDK's `Tools` (so `init`'s `effects`
is `checked`), and maps the exchange like this. Its fixtures pin it: real Ollama answers, with what the runner sent for
each.

| From Ollama | Run event |
|---|---|
| `/api/version`, and the runtime's model | `init`, with the engine's name, version and model |
| an answer's `model`, when it isn't the one asked for | `served_model`, the first time that model answers, before the answer's other events |
| an answer's text, once its `done` line has come | a `turn`, if it has any text |
| an answer's `thinking` | none; the transcript keeps it |
| each `tool_calls` entry | `tool_call` and `tool_result`, from the SDK. A call with no id gets `call-<request>-<position>` |
| a request made again: a connection that failed, dropped or went silent, or status 500, 502, 503 or 504 | `retry`: `network` for the connection, `server` for the status |
| `done_reason` `length` | `result` `error`, reason `output-limit`, naming the window; none of that answer's calls run, and it isn't retried |
| an answer with no tool call | `result` `ok`, with its text |
| any other status, an `error` line, `maxTurns` reached, or retries spent | `result` `error`, with Ollama's message. Its `reason`: a 400 saying the request exceeds the context size → `context-length`, 401 or 403 → `authentication`, 404 → `configuration`, an `error` line → `engine`, `done_reason` `length` → `output-limit`, `maxTurns` → `turn-limit`, retries spent → the last retry's reason, any other status → `other` |
| each answer's `prompt_eval_count`, `prompt_eval_cached_count` and `eval_count` | summed into `result.usage`. `prompt_eval_count` includes the prompt tokens Ollama took from its cache, which it reports as `prompt_eval_cached_count`: that is `cacheReadTokens`, `prompt_eval_count` less it is `inputTokens`, and `eval_count` is `outputTokens`. If any answer leaves out its cached count, nothing is subtracted and `cacheReadTokens` is left out (see [What usage counts](#what-usage-counts)) |

Its transcript is the first request's body, then before each later request the messages the runner added (the
answer and its `tool` messages), each encoded exactly as inside that request, and every line of every answer: each
record verbatim and once. Every request asks Ollama to refuse a conversation longer than the window rather than cut
it (`truncate` and `shift` `false`), which Ollama 0.12.6 added, so the runner requires it and refuses an older one with
`runner.requirement-unmet`.

### Mapping an engine: the Responses API

The [OpenAI runner](../plugins/runner-openai/README.md) is the same shape as Ollama's, on OpenAI's Responses API: the
service only answers, and the runner holds the conversation and runs the tools with the plugin SDK's `Tools`, so
`init`'s `effects` is `checked`. Its service comes from the actor's runtime, and the key arrives as
`TROUPE_RUNTIME_CREDENTIAL`. Every request is `store: false` and carries the whole conversation: after tool calls, the
response's output items unchanged, then one `function_call_output` per call. Its fixtures pin it, recorded from OpenAI
and from local Ollama's `/v1`.

| From the service | Run event |
|---|---|
| the runtime's model | `init`, with engine `responses` and the model |
| the final event's response (`response.completed`, `.incomplete` or `.failed`, or an `error` event); deltas are read past | everything below |
| its `model`, when it isn't the runtime's | `served_model`, the first time that model answers, before the response's other events |
| its output text | a `turn` |
| its reasoning items | none; the transcript keeps them, and the next request sends them back |
| each `function_call` | `tool_call` and `tool_result`, from the SDK |
| 429, 5xx, a failure whose code is the service's own, or a connection that failed, dropped or went silent | `retry`: `rate-limit`, `server` or `network` |
| completed, with no function call | `result` `ok`, with its text |
| 401, 403, quota, context length, another 4xx, a redirect, a 2xx that isn't a stream, a response it can't read, a refusal, `incomplete`, another failure, `maxTurns` or `maxTotalTokens`, or retries spent | `result` `error`, saying which. Its `reason`: 401 or 403 → `authentication`, quota → `quota`, a `Retry-After` past the cap → `rate-limit`, context length → `context-length`, a redirect, a 404 without OpenAI's shape, `model_not_found` or a 2xx that isn't a stream → `configuration`, a response it can't read → `engine`, a refusal or `content_filter` → `refused`, `max_output_tokens` → `output-limit`, a call without a `call_id` → `engine`, `maxTurns` → `turn-limit`, `maxTotalTokens` → `budget`, retries spent → the last retry's reason, anything else → `other` |
| its `usage` | summed into `result.usage`: cache reads and writes each counted apart from input where every response reports them |
| a `cost` in every response's usage | summed into `result.costUsd` |
| no cost, and a price in `run/start` | `result.estimatedCostUsd`, from the SDK's estimator |

Its transcript records use the contract's [record kinds](#record-kinds): the request body as sent is `sent`; each
stream line unchanged, and the body of an error or of a 2xx that isn't a stream, are `received`; the status with only named headers, and a stream it drops,
are `note`s. The request's URL isn't recorded, since the run's start records the runtime's endpoint. The key, and a
masked echo of it, are masked in everything it sends.

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
  sequence, before `init` or after `result`, a `tool_result` with no earlier `tool_call`, a `served_model` naming
  `init`'s model or one already reported, a `base64` record that isn't base64, a transcript record without a kind
  after the runner accepted `transcript-kinds` or with one when it didn't, or a message over
  `RUNNER_MAX_MESSAGE_BYTES`. troupe never reads such a message with a guess.
- **Cancelling** sends `run/cancel` and gives the runner `RUNNER_CANCEL_GRACE_SECONDS` to exit, then kills it and
  every process it started. The same happens after `shutdown`.
- **Notices** tell the caller what is happening without waiting silently. They have the shape of
  [`notice.schema.json`](../protocol/schemas/notice.schema.json): `run.silent` when no event has arrived for
  `RUN_SILENCE_ANNOUNCE_SECONDS`, once per silence, `run.retrying` for each `retry` event, and
  `run.estimate-dropped` when a result carries an estimate troupe gave no price for (see
  [Cost: reported or estimated](#cost-reported-or-estimated)). `perform` records each in the run's history too
  ([contributing/runs.md](runs.md#run-events)). A `retry` with reason
  `authentication` stops the run at once (`RUNNER_FAIL_FAST_ON_AUTH_RETRY`): a bad credential otherwise looks like
  a hang for minutes.
- **A `context` event is recorded and shown, and nothing more.** troupe raises no notice for it and it doesn't
  change the outcome. Acting on lost content (a gate, an escalation) is later work, and the event carries what it
  will need.
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
| `failed` | The `result` had status `error`. The error's details carry its `reason`, its `notRetried` when it had one, and its message, and its fix says what to do for that reason, after saying to review the run's changes when a retry wasn't safe | `run.error-result` |
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

## Runners with client libraries

A runner may depend on a maintained client library for its engine, and should prefer one to rebuilding the engine's
protocol by hand (decision [#319](https://github.com/troupe-run/troupe/issues/319)). The plugin SDK still depends on
the standard library alone. The library decides none of what the contract or the runner's own spec decides, and
the runner-protocol spec says what the runner keeps, once:

- [Retries follow troupe's named limits, not the library's](../openspec/specs/runner-protocol/spec.md#requirement-retries-follow-troupes-named-limits-not-the-librarys)
- [A runner that uses a library follows no redirect and keeps the credential in its header](../openspec/specs/runner-protocol/spec.md#requirement-a-runner-that-uses-a-library-follows-no-redirect-and-keeps-the-credential-in-its-header)
- [A runner that uses a library stops its request on cancel and end of input](../openspec/specs/runner-protocol/spec.md#requirement-a-runner-that-uses-a-library-stops-its-request-on-cancel-and-end-of-input)
- [A library-backed runner's transcript holds what the library exposes](../openspec/specs/runner-protocol/spec.md#requirement-a-library-backed-runners-transcript-holds-what-the-library-exposes)
- [A runner's dependencies are pinned and licensed compatibly with Apache-2.0](../openspec/specs/runner-protocol/spec.md#requirement-a-runners-dependencies-are-pinned-and-licensed-compatibly-with-apache-20)
- [A weak-copyleft dependency is used only unmodified, as its own package](../openspec/specs/runner-protocol/spec.md#requirement-a-weak-copyleft-dependency-is-used-only-unmodified-as-its-own-package)

The design that adds a library says how the runner keeps each one (for example `max_retries=0` with troupe's own
loop), and what its transcript leaves out compared with the bytes on the wire. The runner's tests show each one
against a fake service.

A runner with a library is an optional extra of `troupe-run`, so an install only carries the libraries of the runners
it uses. Adding one takes these steps, and each has a check that fails when it's missed:

| Step | The check that fails without it |
|---|---|
| Add the library to the plugin's `dependencies`, and run `uv lock` | `uv sync --locked` in `scripts/check.py` |
| Move the plugin from `troupe-run`'s `dependencies` to an extra named exactly after its runner (`lm-studio`, not the library's `lmstudio`), and add the same entry to `all` | The bundle check (`scripts/bundle.py`) |
| Set `in_extra=True` on the runner's entry in core's runner table (`troupe.core.interim.RUNNERS`) | The bundle check |
| While the plugin hasn't released, so the bundle names it bare, keep the bundle's commits out of release pull requests | The release configuration check (`scripts/release_config.py`) |
| Add a row for the extra to the list on the [install page](../docs/opening-night/install.md) | The docs check (`scripts/tests/workspace/test_install_docs.py`) |
| Check every package the library pulls in has a licence on one of the two tiers of `scripts/licences.toml`. Add one only in a reviewed change, with its reason | The licence check (`scripts/runner_licences.py`) |

An actor on a runner that isn't installed is refused, naming `troupe-run[<runner>]`, at `troupe config set` on that
actor, at `troupe perform` and at `troupe init --audition` (its error is in [runs.md](runs.md#notices-and-errors)). Config's other commands and
merges leave that actor's options unchecked instead, so one teammate's actor doesn't block everyone else. CI's
install check installs `troupe-run[all]` on every platform and Python, and rehearses an audition on every runner.

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
