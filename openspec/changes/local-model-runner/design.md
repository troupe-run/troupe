# Design

## Context

See proposal.md for why. What shapes the approach:

- **The contract and its SDK already exist.** `troupe_plugin_sdk.runner` has the contract's types, and
  `troupe_plugin_sdk.tools.Tools` has the seven file tools. They check every call against the declaration
  (`checked`), keep paths inside the workspace or scratch, cap their output, and number each call's `tool_call` and
  `tool_result` events. `Declaration.from_run_start` reads the effects. contributing/runners.md says a runner whose
  engine returns tool calls "gives them to the plugin SDK's `Tools`". This is the first runner to do that for a real
  model.
- **Ollama's `/api/chat`** (checked against docs.ollama.com, 2026-11-04) takes `model`, `messages` (roles `system`,
  `user`, `assistant`, `tool`), `tools` (function definitions with a JSON Schema), `stream` (default true), `options`
  (`num_ctx`, `temperature`, `seed`, …) and `think`. It streams NDJSON: each line has a partial `message` (`content`,
  `thinking`, `tool_calls`), and the last has `done: true`, `done_reason`, durations, `prompt_eval_count` and
  `eval_count`. Tool calls have `function.name`, `function.arguments` (an object) and an `index`, but no id. Results go
  back as `{"role": "tool", "tool_name": ..., "content": ...}`. Ollama is stateless, so each request carries the whole
  conversation. `GET /api/version` gives the version, and `POST /api/show` gives a model's details, including
  `capabilities` (`tools` among them). Errors are `{"error": "..."}` bodies with an HTTP status, or an `error` line in
  a stream.
- **The interim runner table** (`troupe.core.interim.RUNNERS`) is the only place a runner name becomes a command, and
  it names the package whose `schemas/` config checks options against. The audition table (`troupe.core.audition`)
  gives each runner an example actor.
- **The host** gives a runner `RUNNER_START_TIMEOUT_SECONDS` (30) for the handshake and `run/start` together, and
  `RUNNER_CANCEL_GRACE_SECONDS` (10) to exit after a cancel or shutdown.
- No Ollama is installed on the development machine (checked 2026-11-04), and LM Studio's `lms` is. Fixtures from a
  real Ollama need one installed, and a model pulled (task 4.2).

## Goals / Non-Goals

**Goals:**

- A runner whose every behaviour can be tested offline against a fake endpoint, on Linux, macOS and Windows.
- The contract changes where the runner found it shaped around an engine that holds its own conversation, and
  nowhere else.

**Non-Goals:**

- Sharing a loop with #162's runner. Each runner keeps its own engine client, and what they share is the SDK. If
  #162 shows the loop itself is worth sharing, moving it into the SDK is a later change.
- Ollama's `/api/generate`, embeddings, images, structured output (`format`) and `keep_alive`.
- Starting Ollama, pulling a model, or choosing a model for the person beyond the audition's example.
- Restricting endpoints. That is policy's job, later (owner, 2026-11-04).
- Choosing what a run *should* do when an engine runs out of context or cuts its output, for every runner: that's
  Decision #279. This change ships the conservative default (D15), which loses nothing and which #279 can change.

## Decisions

### D1. One plugin for one engine: `plugins/runner-ollama/`

The plugin is `troupe-runner-ollama`, with the module `troupe_runner_ollama` and the runner name `ollama`. #56 left
open whether to build one plugin with an adapter per engine. The split settles it. LM Studio goes through #162's
OpenAI-style runner, so a "local" plugin would hold one engine. Its options would also need an `engine` switch whose
branches share nothing but the SDK.

- *Alternative:* `runner-local`, with `engine: ollama`. Rejected: it names a deployment, not an API, and Ollama on
  another machine (D10) isn't local at all.

### D2. The standard library's `http.client`, with no dependency

The runner talks to Ollama with `http.client.HTTPConnection` or `HTTPSConnection`. The plugin depends on the SDK
alone, as the other runners do, so the bundle gains nothing.

- `urllib.request` was rejected for two reasons. It applies proxies from the environment, which the runner has none
  of anyway (D10). And it hides the connection, which cancel has to close (D3).
- `httpx` or `requests` were rejected: a dependency that every install of troupe-run would inherit, for one runner's
  streaming GET and POST.
- Streaming is `response.readline()` against a socket timeout of `STREAM_IDLE_TIMEOUT_SECONDS`. A line longer than
  the contract's `RUNNER_MAX_MESSAGE_BYTES` can't be sent on anyway, so reading is capped at a named
  `LINE_MAX_BYTES` (16 MiB). A longer line is a stream error (D9), not an unbounded read.

### D3. Two threads: the protocol on the main thread, the loop on a worker

The main thread reads standard input and answers JSON-RPC, as the scripted and Claude Code runners do. After it
acknowledges `run/start`, a worker thread runs the conversation (D5). Each message goes to standard output under one
lock, so the two threads' lines never interleave.

- **Stopping:** `run/cancel`, end of input and `shutdown` set a stop flag, then shut down the socket of the request
  in flight (`socket.shutdown(SHUT_RDWR)`, then `close`). That wakes a blocked `readline` on every platform. Once the
  flag is set, the worker sends nothing more. It checks the flag before each request and each tool call, and after
  each line. A tool call already running finishes, since the SDK's tools are synchronous and bounded by their file
  limits, but its events aren't sent. The main thread waits up to `STOP_GRACE_SECONDS` (2) for the worker, then
  exits. The worker is a daemon thread, so it can't keep the process alive.
- **Exit codes:** 0 after answering `shutdown` or `run/cancel`, and at end of input. 1 when the runner itself fails
  (an exception in the loop), after a `log` error and an `error` result if no `result` was sent. The host treats a
  non-zero exit after an `ok` result as `run.unclean-exit`, so a bug can't pass as a success.
- No process is started, so there is no OS seam module and no signal handling. That's simpler than Claude Code's
  runner, and the same on all three platforms.
- *Alternative:* `asyncio` with a hand-written HTTP/1.1 client. Rejected: it reimplements chunked decoding and TLS
  setup that `http.client` already has, to save one thread.

### D4. Preflight before acknowledging `run/start`

The runner first parses the options (D11), then makes two requests, each with a socket timeout of
`PREFLIGHT_TIMEOUT_SECONDS` (10, well under the host's 30):

1. `GET /api/version`. A connection refused, a timeout, or a body without a `version` string means
   `ollama.unreachable`, naming the endpoint (without user info, which D10 refuses anyway).
2. `POST /api/show` with `{"model": ...}`. A 404 means `ollama.model-not-found`, with the fix
   `ollama pull <model>`. A `capabilities` list without `tools` means `ollama.model-without-tools`. A missing
   `capabilities` field, which is the case in Ollama versions older than the field, is refused the same way. Its
   problem says Ollama didn't say whether the model can call tools, and the fix names upgrading Ollama: refuse
   rather than guess. The same answer gives the model's maximum context, `model_info["<arch>.context_length"]`
   where `<arch>` is `model_info["general.architecture"]`, which D15 uses.

Only then does the runner answer `run/start`, so a misconfigured actor ends `could-not-start` with the runner's own
error, rather than a run that fails on its first request. The preflight requests aren't transcript records: they come
before the run starts, and the version and the model are in `init`.

### D5. The conversation and the loop

- **The first request:** `{"model", "messages", "tools", "stream": true}`, plus `options` (`num_ctx`, `temperature`,
  `seed`) and `think` when they're set (D11). `messages` is the character as a `system` message, when there is one,
  then the direction as a `user` message. `tools` is `Tools.offered()`, each as
  `{"type": "function", "function": {"name", "description", "parameters"}}`.
- **Reading an answer:** the runner gathers `content`, `thinking` and `tool_calls` across the stream's lines until
  the line with `done: true`. It sends no event until that line (D9 depends on this).
- **After an answer:** it appends one `assistant` message to the conversation: `content`, `thinking` when there was
  any, and `tool_calls` as Ollama gave them. Ollama's tool-calling docs say to send all three back. It sends the
  answer's `turn` event if the text isn't empty. Then, for each call in order:
  1. it takes the call id: Ollama's `id` when the call has a non-empty one, otherwise `call-<request>-<index>`, where
     `<request>` counts the run's requests from 1;
  2. it runs `Tools.run(call_id, name, arguments, numbering)`, which checks the call, carries it out and numbers its
     two events;
  3. it sends those events and appends `{"role": "tool", "tool_name": name, "content": output}`.

  A call with no `function.name` still gets a call id, and goes to the SDK with an empty name, which makes it an
  unknown tool. A call whose `arguments` is a string goes to the SDK as text, which parses it or refuses it.
- **Ending:** an answer with no tool call ends the run. The runner sends an `ok` result whose message is the answer's
  text, cut (D8), or `(no text)` when it's empty. Otherwise it makes the next request, unless `maxTurns` requests have
  been made, in which case it sends an `error` result: `stopped after <n> turns (maxTurns); the model was still
  calling tools`.
- `done_reason` `length`, meaning the output limit was hit, is a `log` warning. The answer is still used. Whether a
  cut answer should fail the run is #279's question 4.
- Before carrying out an answer's tool calls, the runner checks it against the window (D15).

### D6. Mapping onto run events

| Ollama | Run event |
|---|---|
| preflight's version and the options' model | `init`: runner `ollama` and its version, engine `{name: "ollama", version, model}`, `tools` from `Tools.names()`, `effects: "checked"` |
| an answer's text, at its `done` line | one `turn` (`assistant`), when the text isn't empty |
| an answer's `thinking` | none; the transcript keeps it |
| each `tool_calls` entry | `tool_call` and `tool_result`, from the SDK (D5) |
| a request made again | `retry` (D9) |
| `done_reason` `length` | `log` warning |
| prompt tokens at the window (D15) | `result` `error`, and the answer's calls aren't carried out |
| an answer with no tool call | `result` `ok` |
| `maxTurns` reached, an error not retried, retries spent | `result` `error` |

The `result` carries `turns` (the requests made), `durationMs` (from `run/start`'s answer to the result) and `usage`:
`inputTokens` is the sum of `prompt_eval_count` and `outputTokens` the sum of `eval_count`, over every answer that
reported it. A counter no answer reported is left out. It carries no `costUsd`, since nothing tells the runner a
price. What the contract does when a service has a price is #162's question.

### D7. The transcript (the first contract amendment)

The contract said the transcript is "the engine's native output". For Claude Code, that is the whole run, because
Claude Code holds the conversation and runs the tools, so its output includes each tool's result. Here the runner
holds the conversation, and the tool outputs exist only in what it sends Ollama. Recording only Ollama's output
breaks the contract's own rule that "full inputs and outputs belong in the transcript".

Recording every request body verbatim would keep everything, but each request re-sends the whole history. Fifty
turns of large file reads would grow the transcript with the square of the run, towards
`RUN_TRANSCRIPT_MAX_BYTES`. So the records are:

1. the first request's body, the exact bytes sent;
2. before each later request, each message appended since the previous one: the `assistant` message and the `tool`
   messages. Each is serialised exactly as it is inside the request body (the same `json.dumps` call and separators),
   so the record is verbatim what was sent;
3. every line of every answer, without its line ending, and every error body. A line that isn't UTF-8 is sent
   `base64`.

Every record is a JSON object in Ollama's own vocabulary, in the order it was sent or received. Anyone reading the
transcript can rebuild every request, since request *n* is the first request's messages plus records 2 up to *n*. A
record that leads to an event is sent before that event.

The contract change (runner-protocol, "The native transcript is a separate stream") is wording only: a runner that
holds the conversation also records what it adds to it, verbatim, once. `run-transcript.schema.json`'s description
says the same. The wire shape doesn't change. The scripted runner replays recordings, and Claude Code's records are
already its engine's output, so neither needs a change.

- *Alternative:* add `origin: "runner" | "engine"` to `run/transcript`. Rejected for now. The host stores records as
  lines and never interprets them, so the field would need a stored form, and the records' own shapes (a request
  body, a message, a stream line) already tell them apart. If a reader needs it, it can be added while the contract
  is version 0.

### D8. Summaries

Event text is cut with the SDK's `fit` and `cut`, the same as the SDK's tool events: `turn.text`, `result.message`,
and `log` and `retry` messages are cut to the SDK's summary limit and to `limits.eventMaxBytes`, saying how many bytes
were left out.

### D9. Retries (the second contract amendment)

The contract said "when the actor's engine retries". Claude Code retries its API calls and reports them. Here the
runner is the engine's client, so its own retries are the ones to report. The contract change is wording only.

- **Retried:** a connection that fails or drops before the `done` line, a stream silent for
  `STREAM_IDLE_TIMEOUT_SECONDS` (300), and a line that isn't a JSON object. Each of these is reason `network`. Status
  500, 502, 503 or 504 is reason `server`.
- **Not retried:** any other status, and an `error` line in the stream. Ollama reports a model that can't run, or an
  input it refuses, this way, and trying again gives the same answer. These end the run with an `error` result
  holding Ollama's `error` text, or the status and body when there's no `error` field.
- **How:** up to `RETRY_MAX_ATTEMPTS` (3) attempts per request. The delay before attempt *n*+1 is
  `RETRY_DELAY_SECONDS × 2^(n-1)` (1, then 2). Each retry is a `retry` event with `attempt` *n*, `maxAttempts`, the
  delay, the reason, and a message naming the failure. The stop flag is checked while waiting.
- No event is sent before an answer's `done` line, so a retry never leaves half an answer's events behind. The
  failed attempt's lines are already in the transcript, which records what happened.
- Ollama isn't a hosted service and sends no 429 or authentication failure, so neither reason is mapped. #162 maps
  them.

### D10. The endpoint and the environment

- `endpoint` defaults to `DEFAULT_ENDPOINT` (`http://127.0.0.1:11434`) in the plugin's `defaults.py`. The URL's
  scheme is `http` or `https`, and it has a host and an optional port. Its path is empty or `/`, and it has no query,
  fragment or user info. User info is refused so a password can't be committed to config, and the refusal never
  echoes it. Requests go to `<endpoint>/api/...`.
- Any host is accepted (owner, 2026-11-04). A run can therefore send the workspace's contents wherever config
  points. The README says so, and restricting it is left to policy.
- **The runner table names no environment variables**, as for the scripted runner. Ollama's own `OLLAMA_HOST` is
  never read: the contract says configuration comes only from `run/start`, and a variable that silently moved the
  endpoint would make a run depend on whoever ran it. `http.client` reads no proxy variables, so none are needed.

### D11. Options, defaults and errors

| Option | Shape | Default | Becomes |
|---|---|---|---|
| `model` | non-empty string, required | — | `model` |
| `endpoint` | URL (D10) | `DEFAULT_ENDPOINT` | where requests go |
| `maxTurns` | integer, 1 to 1000 | `MAX_TURNS` (50) | the loop's limit (D5) |
| `contextLength` | integer ≥ 1, at most the model's maximum (D15) | `DEFAULT_CONTEXT_LENGTH` (16384), lowered to the model's maximum | `options.num_ctx`, always |
| `temperature` | number ≥ 0 | Ollama's own | `options.temperature` |
| `seed` | integer | Ollama's own | `options.seed` |
| `think` | boolean, or `low`, `medium` or `high` | Ollama's own | `think` |

`defaults.py` holds `DEFAULT_ENDPOINT`, `MAX_TURNS`, `DEFAULT_CONTEXT_LENGTH`, `CONTEXT_MARGIN_TOKENS`, `PREFLIGHT_TIMEOUT_SECONDS`, `STREAM_IDLE_TIMEOUT_SECONDS`,
`LINE_MAX_BYTES`, `RETRY_MAX_ATTEMPTS`, `RETRY_DELAY_SECONDS` and `STOP_GRACE_SECONDS`, each documented in the README.

The error codes are in `errors.schema.json`, each with closed `details`:

| Code | JSON-RPC | `details` |
|---|---|---|
| `ollama.unknown-option` | -32602 | `where` |
| `ollama.invalid-options` | -32602 | `where` |
| `ollama.unreachable` | -32000 | `endpoint` |
| `ollama.model-not-found` | -32000 | `endpoint`, `model` |
| `ollama.model-without-tools` | -32000 | `model`, `capabilities` (when Ollama gave them) |

`parse_options` follows the Claude Code runner's `options.py`, and a hypothesis test checks that it agrees with the
schema.

### D12. Testing against a fake Ollama

- **`tests/fake_ollama.py`** is a `ThreadingHTTPServer` on `127.0.0.1`, port 0. It serves `/api/version` and
  `/api/show` from its settings, and serves `/api/chat` from a queue of scripted answers. Each answer is a status, a
  list of lines with optional delays, and an optional mid-stream close. It records every request body and notices
  when a client closes the connection. Each test starts one fake and gives the runner its URL as `endpoint`.
- **The harness** follows `claude_harness.py`. It starts the runner as a process and validates every message against
  the contract, with the runner's schemas bound.
- **Fixtures** (`fixtures/ollama/<name>/`): `exchange.jsonl` (the records the real exchange produced),
  `provenance.json` (Ollama's version, the model, the date, the direction and the capture command) and
  `events.json` (the run events the runner sends for it, hand-written and reviewed). The fake serves a fixture's
  answers, and a test checks the runner's transcript and events match it exactly. The captured set:
  - `success-with-tools`: `Write`, then a final answer;
  - `refused-by-effects`: a write outside the declaration, refused by the SDK, then a final answer;
  - `thinking`: a thinking model's answer;
  - `model-not-found`: `/api/show`'s 404 body;
  - `no-tools-capability`: `/api/show` for a model without `tools`.

  The failure shapes a real Ollama won't produce on demand are hand-written and say so in their provenance: a 503,
  a dropped connection, an `error` line and a silent stream. This is the same rule as Claude Code's fixtures.
- **`tools/capture_ollama.py`** drives a real Ollama, with no credential, in a temporary workspace, through the
  runner's own client, and writes a fixture. It refuses to run if the endpoint isn't loopback, so a capture can't
  record someone else's server by mistake.
- **Core's tests** get `ollama_stand_in.py`, a small copy of the fake that serves one fixture, as `claude_stand_in.py`
  does for Claude Code. Core's tests import nothing from a plugin's tests. It is used for the conformance suite, the
  host's end-to-end test, and `perform` and audition tests.

### D13. The audition: `qwen3:4b`

`troupe.core.audition` gets `OLLAMA_AUDITION_MODEL = "qwen3:4b"` and an `ollama` entry: options `{"model": ...}`,
`effects.write: ["**"]`, `expect: []`, and the Claude Code audition's character. `qwen3:4b` calls tools, is about
2.5 GB, and runs on a laptop without a GPU.

- `llama3.2:3b` was rejected because it's weaker at tool calls. `qwen3:8b` (about 5 GB) was rejected because it's
  slower to pull for a first try.
- The model is named in one place, so changing it is a one-line change.
- The perform step's note says Ollama must be running and gives `ollama pull qwen3:4b`. The CLI takes the model from
  the audition's change entries (`actors.lead.options.model`), which the init result already carries, so the client
  protocol doesn't change.

### D14. The live test

`packages/troupe/tests/test_ollama_live.py` is skipped unless `TROUPE_LIVE_OLLAMA=1`. `TROUPE_LIVE_OLLAMA_MODEL`
names the model, defaulting to the audition's, and the endpoint is the default. It performs an actor asked to write
`out/hello.txt` with `write: ["out/**"]`, and asserts what the runner controls:

- every message validates;
- the run reaches a `result`;
- the outcome is `succeeded` or `failed`, never `crashed`.

It prints whether the model actually wrote the file, but doesn't assert it, because small models are flaky at tool
use (#16, option B). CI never sets the variable. The owner runs it once (task 9.2).

### D15. The context window is always set, and never silently outgrown

Ollama doesn't refuse a conversation longer than its window (`num_ctx`). It drops the oldest part and carries on,
and with troupe's own loop the oldest part is the character and the direction. Its default window is small in many
versions, and one `Read` can return 256 KB. So a run could pass the window in a few steps and "succeed" at a task it
can no longer see. What a run *should* do then, for every runner, is Decision #279. This change does what's needed
whatever #279 decides: the runner knows the window, and it never carries on past it without saying so. The default
it ships, stopping the run, is the one that loses nothing.

- **The window is always sent.** `options.num_ctx` is `contextLength`, or `DEFAULT_CONTEXT_LENGTH` (16384) lowered
  to the model's maximum from the preflight's `/api/show` (D4). It is never left to Ollama's default, which differs
  between versions and machines. A `contextLength` above the model's maximum is refused at preflight. When Ollama
  reports no maximum, the value is used as it is.
- **Why 16384:** the KV cache grows with the window. For `qwen3:4b` that's about 2.4 GB at 16384 and about 4.8 GB at
  32768, on top of the model. 16384 holds a direction, a character and several file reads, and fits a laptop. It's
  a named setting, and the README says when to raise `contextLength`.
- **Detecting it:** after each answer, the runner compares the prompt tokens that answer reports with the window.
  It stops when they're within `CONTEXT_MARGIN_TOKENS` of it, because a truncated prompt is filled to the window.
  "Prompt tokens" means `prompt_eval_count`, plus a separately reported cached count if there is one. Which of
  those Ollama reports is the open question task 4.3 settles from a real capture (`context-overflow`, run with a
  small `contextLength`). Task 4.3 also sets `CONTEXT_MARGIN_TOKENS` from what the capture shows, and the detection
  isn't built (5.1) until it has. If the counts can't show a truncation, the owner is asked before going on, since
  the spec's requirement would then need another mechanism.
- **Stopping:** the overflowing answer's tool calls are not carried out, since they come from a model that can no
  longer see its direction. No further request is made. The `result` is `error`: `the conversation outgrew the
  model's context window of <n> tokens; Ollama drops the start of the conversation, the direction among it. Raise
  contextLength, or give the actor a smaller task.`
- **Alternatives:**
  - Estimating the next request's tokens from its bytes, to stop before sending it. Rejected: a byte count is only a
    loose bound (one token is one to several bytes), so it would stop runs far too early or miss overflows.
  - Compacting the conversation (dropping old tool output, keeping the character and direction). Deferred to #279:
    it changes what the model sees, which is a product decision.

## Risks / Trade-offs

- **Ollama silently cuts the conversation to its context window.** → D15: the runner always sets the window, and
  ends the run when an answer reaches it. The remaining risk is that Ollama's counts don't show a truncation
  clearly. Task 4.3 checks that against a real capture before the detection is built, and asks the owner if they
  don't. A run that stops at the window loses no data, but it is a failed run. #279 decides whether something better
  than stopping is wanted.
- **Small models are bad at tool calls.** They describe a call in text instead of making one, or give arguments
  that don't fit. → A malformed call is an SDK error result that the model can recover from. A model that does
  nothing ends `ok`, and `expect` and the effect audit are what catch it. The live test doesn't assert the model's
  competence.
- **Model loading is slow and silent.** Ollama streams nothing while it loads a model, which can take minutes on
  the first request. → The host's `run.silent` notice says so after 30 s. `STREAM_IDLE_TIMEOUT_SECONDS` is 300 so a
  load isn't mistaken for a dead stream, and it's a named setting.
- **Any endpoint is accepted.** → Documented. The decision is the owner's, and policy is where it'll be restricted.
- **Two threads and a socket close is the cancel path.** → It's tested on all three operating systems against a
  fake that streams slowly. The test checks that the fake saw the close, that no event follows the acknowledgement,
  and that the runner exits within the host's grace.
- **The transcript isn't every request byte for byte.** → D7 records every byte that wasn't sent before, and says
  how to rebuild each request. The contract's wording now says so.

## Migration Plan

The change adds a runner and only rewords the contract, so nothing existing migrates. The bundle (`troupe-run`)
gains `troupe-runner-ollama`, bare until its first release, as each new package was. After this merges, an
infrastructure pull request adds the `ollama-runner` spec's Purpose to `oob/troupe-spec-purposes.json`.

## Open Questions

- Whether Ollama reports a separate cached prompt count. Task 4.3 finds out, because D15 needs it. If there is one,
  mapping it to `cacheReadTokens` in `usage` is a follow-up change. This change maps only the two counters the spec
  names.
- What a run should do when an engine runs out of context or cuts its output, beyond D15's default: Decision #279.
