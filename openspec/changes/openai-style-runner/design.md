# Design: the OpenAI runner

## Context

See proposal.md for why. What the design builds on:

- **The runner contract, version 0** (`protocol/schemas/runner/`, `contributing/runners.md`): JSON-RPC over stdio, one
  run per process, `init` first, `tool_call`/`tool_result` pairs, `retry` with a fixed list of reasons, one `result`
  with optional usage and `costUsd` ("as the engine reports it"), and a transcript of opaque native records.
- **The plugin SDK** (`troupe-plugin-sdk`, #240): the contract's types, `Declaration.from_run_start`, and
  `Tools`, which checks a model's tool call against the declared effects, carries it out and returns the event
  pair and the text for the model. It depends only on the standard library and does no I/O but the workspace.
- **The Claude Code and Ollama runners** are the pattern to follow: a self-contained plugin with closed options, a
  `defaults.py` holding every limit, published options and error schemas, fixtures that pair real output with
  expected events, a capture tool, and an opt-in live test. The Ollama runner's process (#277) is the closest: the
  main thread answers troupe, a worker runs the loop, and one lock covers every write.
- **Runtimes (#278, PR #287)** say where an actor's service comes from: `runtimes.<name>` with an endpoint, a model
  and a credential that is the name of an environment variable, resolved from troupe's built-ins (`openai`,
  `ollama`, `lm-studio`), the theatre's config and the person's environment (`TROUPE_RUNTIME_<NAME>_...`). An actor
  may set its own `model`. troupe refuses a credential over plain HTTP to another machine, one shorter than 8 bytes,
  and an unset variable, all before a run is recorded, and masks the credential in what it stores. That config can
  choose the endpoint, and the variable, is an accepted risk for now, with policy to limit both later (#287's
  design D7; owner, 2026-11-04).
- **The API** (#290, owner, 2026-11-05): OpenAI's Responses API, only (D15).
- **Order:** the owner chose (2026-11-04) to build this runner on contract version 0 as it stands and file each gap it
  finds.

## Goals / Non-Goals

**Goals:**
- A runner that works against OpenAI, and against any service that serves the Responses API (local Ollama does),
  without per-host code.
- Every way a hosted service fails maps to one defined, tested behaviour.
- The credential can't leak into anything troupe keeps, even when the service echoes it.
- The contract's gaps are found and written down precisely, not papered over.

**Non-Goals:**
- Chat Completions (#290; the work built for it is prior art for other runners, noted on #56).
- Choosing, resolving or validating the runtime (#278), beyond the runner's own defence in depth (D11).
- Estimating cost from a price list (waits on a contract change, D12).
- Parallel tool calls, a shell tool, OpenAI's built-in tools (web search, file search and the like), images and
  audio.

## Decisions

### D1. One plugin, `openai`, separate from #56's

The runner is `plugins/runner-openai`, package `troupe-runner-openai`, module `troupe_runner_openai`, runner name
`openai`. It matches the built-in runtime: an actor reads `runner: openai`, `runtime: openai`. Its error codes are
`openai.<what>`.

It's not an adapter inside #56's plugin, even though Ollama serves the Responses API too: #56 deliberately uses each
engine's native API, and #239 chose separate plugins so the runners test the contract independently. The SDK shares
the code they'd have in common.

### D2. The runtime's hand-off, as #278 gives it

Checked against PR #287 (task 1.1). The runner gets:

- in `run/start`, `runtime`: `name`, `endpoint` (the base URL; the runner adds `/responses`), `model` (already
  resolved from the person's environment, the actor and the runtime), and `credential`, a boolean;
- when `credential` is true, the value in its environment as `TROUPE_RUNTIME_CREDENTIAL`, read with the SDK's
  `runtime_credential`, which refuses a `run/start` and an environment that disagree
  (`openai.credential-mismatch`).

The runner table gives `openai` `runtime="required"`, so config refuses an actor on it that names no runtime; the
runner still refuses a `run/start` without one (`openai.no-runtime`), from a host that doesn't keep the contract. The
runner touches the runtime in one module (`runtime.py`).

The built-in `ollama` runtime's endpoint is Ollama's own API (`http://127.0.0.1:11434`, for #56's runner), not its
OpenAI-style one under `/v1`. An `openai` actor on it gets a 404, so a 404 without OpenAI's error shape names the URL
it tried and says the endpoint must be the base its Responses API is served under (D8).

Alternatives: endpoint and model in this runner's options (the issue's first wording) was overtaken by the owner's
runtime model, which keeps a service's settings in one place for every runner; reading `OPENAI_API_KEY` directly
would let config choose where a key goes (#160's finding).

### D3. HTTP from the standard library, behind one module

Requests go through `urllib.request` in `service.py`, the only module that does network I/O, with a redirect handler
that refuses every redirect (urllib otherwise follows them and resends the `Authorization` header). urllib also
honours `HTTPS_PROXY` and `NO_PROXY`, and uses the platform's TLS trust store, or `SSL_CERT_FILE`/`SSL_CERT_DIR`. A
loopback endpoint never goes through a proxy. The socket is captured as it connects, so the stream timeout can be set
once the headers arrive and another thread can shut it down; urllib drops the connection's own reference by then.

Alternatives: `httpx` gives nicer timeouts and streaming, but is a dependency every install carries for one module;
the `openai` SDK retries on its own terms, follows its own redirect and header rules, and hides the wire bytes the
transcript has to keep. The SDK and the other runners depend on nothing outside the standard library and the SDK,
and this keeps it so.

### D4. Streamed responses, read to their final event

Every request sets `"stream": true`. Streaming gives three things a single response can't: events while the model
works (so troupe's silence announcement means something), a stream timeout that tells a stalled service from a slow
one, and the broken-stream case the issue names.

The stream is server-sent events: an `event:` line naming the type, a `data:` line holding it as JSON (its `type`
says the same), and a blank line. There is no `[DONE]` line: the stream ends after its final event. Both recordings
(D15) have this shape.

**The reply is the final event's response object**, not something accumulated from deltas. `response.completed`,
`response.incomplete` and `response.failed` each carry the whole response: its `status`, its `output` items
(`message`, `function_call`, `reasoning`), `incomplete_details`, `error` and `usage`. The deltas
(`response.output_text.delta`, `response.function_call_arguments.delta`, `response.reasoning_summary_text.delta`)
only show the model working; the runner reads past them. This is simpler than building items from deltas, and it can't
disagree with the service's own record of what it sent. An `error` event, which the service can send mid-stream,
counts as a final event too, with its code and message.

A stream that ends without a final event, holds a `data:` line that isn't JSON, or holds an event whose type it can't
read is broken (D8). The partial response is dropped whole, tool calls included, never carried out.

### D5. Threads, one write lock, and a worker, as the Ollama runner does

The main thread reads troupe's messages and answers them, checking everything that can be refused before it answers
`run/start`. Then a worker thread sends `init` and runs the loop. Both threads write to standard output one whole line
at a time under one lock, and every line goes through the run's mask first (D11). Stopping (on `run/cancel`, end of
input or `shutdown`) sets a flag under that lock before the answer is written, so nothing the worker sends can follow
it; then the call in flight is aborted, which wakes the worker wherever it waits. The runner exits within its own
named grace, below troupe's cancel grace, whether or not the worker has finished.

Alternative: asyncio with a thread per request. It's no simpler, and the Ollama runner's structure is already tested
on all three platforms.

### D6. The tool loop, stateless

```
instructions = runner instructions + character?
input = [user(direction)]
for turn in 1..maxTurns:
    response = request(instructions, input)   # retries inside (D8)
    send turn(output text) if any
    refusal / incomplete / unknown status: error result
    no function_call in output: ok result(output text); stop
    for call in function_calls(output):       # in order
        step = tools.run(call.call_id, call.name, call.arguments, numbering)
        send step.events
    input += response.output                  # unchanged, reasoning included
    input += [function_call_output(call_id, step.output) for each call]
    tokens used >= maxTotalTokens: error result (budget); stop
error result (turn limit)
```

Every request is `store: false`, names no `previous_response_id`, and has `include: ["reasoning.encrypted_content"]`.
So the service keeps nothing of the run, every request carries the whole conversation, and a reasoning model's
reasoning comes back encrypted, to be sent back unchanged. Both OpenAI and local Ollama continued the conversation
this way in the recordings (D15). Sending the output items back as the service gave them, not rebuilt, keeps whatever
the service needs from them (ids, encrypted reasoning) without the runner having to know it.

`Tools.for_declaration(Declaration.from_run_start(params))` makes the tools; `Tools.offered()` gives the definitions,
sent as `{"type": "function", "name", "description", "parameters", "strict": false}`. The Responses API makes a
function tool strict when the request doesn't say: OpenAI's recording echoed the tool back with `"strict": true`. Strict
mode needs every property required and no others, and the SDK's tools have optional fields (`Read`'s `offset` and
`limit`), so the runner says `false` (found while building, 2026-11-06).
The calls of one response run in order, one at a time: the SDK's tools share a workspace, and order is what the model
asked for. A `function_call` without a `call_id` can't be answered (its output has nowhere to go), so it ends the run
with an error naming its tool, rather than the runner inventing an id the service wouldn't know.

The runner's fixed instructions, in `defaults.py`, tell the model it works in a workspace only through the tools
offered, and that replying without a tool call ends the run, with that reply as its summary.

### D7. Limits, each named once

`defaults.py` holds every limit of the runner's own:

| Setting | Default | Limits |
|---|---|---|
| `DEFAULT_MAX_TURNS` | 50 | Requests in a run, when the options don't set `maxTurns` |
| `DEFAULT_MAX_TOTAL_TOKENS` | 1,000,000 | Input plus output tokens over the run, when the options don't set `maxTotalTokens` |
| `MAX_ATTEMPTS` | 5 | Attempts at one request, the first included |
| `RETRY_BASE_DELAY_SECONDS` | 1 | The first retry's delay, doubled each time |
| `RETRY_MAX_DELAY_SECONDS` | 60 | The longest delay, `Retry-After` included; past it, the run ends |
| `CONNECT_TIMEOUT_SECONDS` | 30 | Connecting and getting the response's status |
| `STREAM_TIMEOUT_SECONDS` | 120 | Silence between two reads of a response's stream |
| `SUMMARY_MAX_BYTES` | 4096 | One summary field, before `eventMaxBytes` cuts it further |
| `STOP_GRACE_SECONDS` | 5 | The worker's time to stop after a cancel, below troupe's 10 |
| `STREAM_LINE_MAX_BYTES` | 16 MiB | One line of a stream; a longer one counts as a broken stream |
| `ERROR_BODY_MAX_BYTES` | 1 MiB | How much of an error's body is read |
| `SERVICE_FAILURE_CODES` | `server_error`, ... | A failed response's codes that are the service's own, so it's retried (D8) |

The token budget is checked after each response, so a run can go past it by one response; the result says how far.
Input tokens are counted again on every request, since the whole conversation is resent: a long run's input grows
with the square of its turns, which is why the budget counts tokens rather than turns alone. A service's prompt cache
softens the cost, not the count.

Options can set `maxTurns` and `maxTotalTokens`, higher or lower than the defaults. Policy limits on runners don't
exist yet; when they do, they bound these.

**Testing never runs on the real-use defaults** (owner, 2026-11-04). The defaults are sized for real work. Every run
made while building and testing sets low limits through the options, from one place in the plugin's tests
(`TEST_LIMITS`: `maxTurns` 5, `maxTotalTokens` 20,000). That covers the runner tests, fixture replays, conformance,
troupe's perform tests and the live test. A runaway loop or a misread final event then stops within a few turns,
instead of after 50 turns or a million tokens. A test that needs more (the turn-limit test, say) sets its own values
explicitly, and the harness refuses a run that sets neither limit. That the defaults apply when no options are given
is checked by parsing the options, never by running a service on them. Manual tries follow the same rule: the docs'
first example sets the same low limits, and the audition sets its own small ones (10 turns, 100,000 tokens; owner,
2026-11-05).

### D8. Failures

| What the service does | Retried? | What the run shows |
|---|---|---|
| 401, 403 | no | `error` result: the service refused the credential, with its message |
| 429, error code `insufficient_quota` | no | `error` result: the account is out of quota |
| 429 otherwise | yes | `retry` `rate-limit`, delay `Retry-After` if given, else backoff; past the cap, `error` result |
| 400 with `context_length_exceeded` | no | `error` result: the conversation is longer than the model's context |
| any other 4xx | no | `error` result naming the status and the service's message |
| 404 without OpenAI's error shape | no | `error` result naming the URL tried, and that the endpoint must be the Responses API's base, often ending in `/v1` |
| 3xx | no | `error` result naming the status and `Location` (D3) |
| 5xx | yes | `retry` `server` |
| connection refused, reset, DNS, TLS, connect timeout | yes | `retry` `network` |
| stream silent past `STREAM_TIMEOUT_SECONDS`, ended without a final event, or a line that isn't a valid event | yes | `retry` `network`; the partial response is dropped |
| `response.failed` or an `error` event, code in `SERVICE_FAILURE_CODES` | yes | `retry` `server` |
| `response.failed` or an `error` event, any other code | no | `error` result naming the code and the service's message |
| `response.incomplete`, reason `max_output_tokens` | no | `error` result: the output limit |
| `response.incomplete`, reason `content_filter` | no | `error` result: the content filter |
| a `refusal` in an output message | no | `error` result: the model refused, with its words |
| a status the runner doesn't know | no | `error` result naming it |

The error body's shape is OpenAI's (`{"error": {"message", "type", "code"}}`). A body that isn't that shape is quoted
as text, cut to the summary limit. Each `retry` event's `attempt` is the attempt that failed, `maxAttempts` is
`MAX_ATTEMPTS`, and `message` is the status and the service's words.

An authentication failure isn't sent as a `retry` with reason `authentication`, since nothing is retried. troupe's
fail-fast on authentication retries is for engines that retry on their own; here the run ends at once anyway. That
the result can't say *why* in a field is gap 1 (D12).

### D9. Usage and cost on contract version 0

The Responses API's `usage` has `input_tokens`, `output_tokens`, `input_tokens_details.cached_tokens`, and, from
OpenAI, `input_tokens_details.cache_write_tokens` (Ollama's has no write count). Anthropic's `input_tokens`, which the
Claude Code runner maps to `inputTokens`, excludes cache reads and writes. So that the four counters mean the same
whichever runner reported them, `cacheReadTokens` is `cached_tokens`, `cacheWriteTokens` is `cache_write_tokens` when
reported, and `inputTokens` is `input_tokens` less both. That `input_tokens` includes the cache writes is OpenAI's
documented shape for reads and an assumption for writes, which the recordings can't show (both reported 0 writes):
the live test checks it, and if it's wrong only this subtraction changes. That the contract doesn't say what
`inputTokens` counts is gap 3.

`costUsd` is defined as what the engine reports. OpenAI reports no cost, so OpenAI runs have none. A service that puts
a `cost` in usage has it summed, when every response has one. A configured price would give an *estimate*, which
version 0 has no field for (gap 2), so the token budget, not a price, bounds spend.

### D10. The transcript's framing

There's no native output to pass through unchanged: the runner itself conducts an HTTP exchange. Each transcript
record is a JSON object of the runner's own, in order:

- `{"kind": "request", "url": ..., "body": "<the body as sent>"}`
- `{"kind": "response", "status": 200, "headers": {...}}`, with only the headers named in `defaults.py`
  (`retry-after`, `x-request-id`, and the `x-ratelimit-*` family)
- `{"kind": "stream", "line": "<one line of the stream, unchanged>"}`, `event:` and blank lines included
- `{"kind": "body", "body": "<a non-streamed body, such as an error>"}`
- `{"kind": "dropped", "reason": ...}` when a broken stream is abandoned

Bodies and lines are kept as strings, so they're byte-for-byte what crossed the wire, after masking (D11). Request
headers are never recorded. That a runner must invent this framing is gap 4.

### D11. The credential

- The value is read once from `TROUPE_RUNTIME_CREDENTIAL` (D2), kept in memory, and put only in the `Authorization`
  header.
- **Masking:** everything the runner sends troupe (events, transcript records, logs, error data, standard error) goes
  through one function that replaces the credential, and a masked echo of it, with `[credential]`. A masked echo is a
  token that contains a run of `*` and starts with the credential's first four characters or ends with its last four,
  which covers OpenAI's `sk-proj-****...abcd` form. A token never takes in a backslash, so an echo inside a transcript
  record's JSON text keeps the escape after it. A credential shorter than eight characters is masked whole only.
- **Defence in depth on the endpoint:** a runtime with a credential and an `http` endpoint to a non-loopback host is
  refused at `run/start` (`openai.insecure-endpoint`), as troupe already refuses it before the run; redirects are
  refused (D3). Which endpoint config may send a credential to is an accepted risk for now (#287's D7).
- **troupe masks too:** it masks the credential in the transcript and everything else it stores (#287). The
  runner's own masking stays, since a log, an error and stderr are also the runner's to keep clean.
- **Tests** run every fixture and failure mode with a canary credential and scan every byte the runner wrote to
  stdout and stderr for it and its masked forms.

### D12. The contract's gaps, found so far

Candidates, each confirmed while building and then filed as its own issue on the board, and adopted by this runner
when it lands:

1. **A failed result has no reason troupe can act on.** Authentication, quota, rate limit exhausted, context length,
   refusal, output limit, budget and turn limit are all `status: error` with a message. troupe can't tell a person
   "fix your key" from "raise the budget" without parsing text.
2. **No estimated cost.** `costUsd` can only be what the engine reports, so a service that reports no price has no
   cost at all, and a price-list estimate has nowhere to go.
3. **`inputTokens` doesn't say what it counts.** OpenAI's input tokens include cache reads and (D9) writes;
   Anthropic's don't. Each runner subtracts to match Claude Code's, which is a convention, not the contract.
4. **Transcript records have no kind.** A runner that drives an API, rather than an engine with its own output,
   invents a framing (D10), and nothing can read two runners' transcripts the same way.
5. **The model served isn't the model asked for.** Each response names the model that answered (often a dated
   version), after `init` has gone; it can only be a `log`.

#56's runner may find some of these too; filing checks its issues first, so each gap is filed once.

### D13. Testing

- **A fake endpoint** in the plugin's tests: a `ThreadingHTTPServer` on `127.0.0.1` that answers each request from a
  script (a status, headers, a body, a stream of lines with optional pauses, a cut-off or a held-open response, or
  raw byte chunks), and records every request it got with its headers. Its helpers build Responses API streams:
  `event:` and `data:` lines, deltas, and a final event carrying the response object. Tests drive the runner as a
  subprocess; core's tests load the same fake by path (`chat_stand_in.py`, renamed for the Responses API).
- **Fixtures** in `plugins/runner-openai/fixtures/responses/<name>/`: the responses, `expected.json` (events and
  outcome) and `provenance.json` (service, model, date, and recorded, derived or built). Recorded: a two-turn tool loop
  against OpenAI (`gpt-6-luna`, the owner's key, 2026-11-05) and one against local Ollama (0.40.14, `qwen3.5:4b`, no
  key), and a rejected credential from OpenAI with an invalid key (free). A rate limit, a server error, a failed
  response, an incomplete response and a refusal can't be had on demand, so they're built from the recorded shapes
  and OpenAI's documented ones; the broken stream is a recorded success cut short.
- **A capture tool**, `tools/capture_openai.py`, records a fixture's responses and writes its provenance, and scrubs
  the credential and the capturing host's paths.
- **Conformance:** `check_runner`, which can now give a runner a runtime and its credential, with the runner pointed
  at the fake endpoint.
- **The live test**, `TROUPE_LIVE_OPENAI=1`, with the runtime taken from the person's environment, a model pinned in
  the test, and `TEST_LIMITS` (D7). Pointed at local Ollama's `/v1`, it costs nothing.
- **Property tests** for the stream reader (arbitrary splits of a recorded stream into reads give the same reply)
  and the masking function (no output contains the credential, whatever surrounds it).

### D14. Shipping it

The runner joins the `uv` workspace, the typing and lint paths, the import contracts (`plugins import nothing from
troupe`, `plugins are independent of each other`, the OS-modules contract, and an I/O seam contract naming
`service.py`), `scripts/check-paths.toml`, release-please's config and manifest, the `troupe-run` bundle and the
changelog page, each as the other runners were added. `troupe.core.interim.RUNNERS` gains `openai` with its
environment: the proxy variables, `SSL_CERT_FILE` and `SSL_CERT_DIR` (`SYSTEMROOT` comes from the platform minimum),
and `runtime="required"`. troupe adds `TROUPE_RUNTIME_CREDENTIAL` itself when the runtime has a credential (#287).

The audition, in `troupe.core.audition`, names its model in one place (`OPENAI_AUDITION_MODEL`, `gpt-6-luna`: the
cheapest current model, and it calls tools over Responses at its default reasoning), with `maxTurns` 10 and
`maxTotalTokens` 100,000, and `init` prints that `OPENAI_API_KEY` must be set and that a run costs money within that
budget.

### D15. Why the Responses API, and what grounds the shapes here

#290 (owner, 2026-11-05) settled the API on a probe with the owner's key: over Chat Completions, OpenAI's current
models call tools only with `reasoning_effort: none`, and only `gpt-6-luna` and `gpt-6.1-terra` accept that; over
Responses all four (`gpt-6-luna`, `gpt-6.1-terra`, `gpt-6.1-sol`, `gpt-6-astra`) call tools at their default reasoning.
Local Ollama 0.40.14 serves `/v1/responses`, and `qwen3.5:4b` called a tool through it.

The stream format (D4), the stateless continuation (D6) and the usage fields (D9) are taken from two recordings made
for this update, not from memory or the docs alone: a two-turn tool loop against OpenAI's `gpt-6-luna` and the same
against local Ollama's `qwen3.5:4b`, each `store: false`, the second request sending back the first response's output
items and a `function_call_output`. Both continued to a final message. They become fixtures (D13).

What carries over from the Chat Completions build unchanged: `service.py` (with the path changed), the retry and
failure classification for HTTP statuses, masking, options, the runtime hand-off, the runner process and the harness.
What's replaced: the stream reader, the request builder and the loop's continuation, and the usage mapping. The Chat
Completions versions stay in the branch's history as prior art (noted on #56).

## Risks / Trade-offs

- **Only services that serve Responses are reachable** → decided in #290; hosts that serve only Chat Completions need
  another runner, a new issue if one is wanted.
- **The final event carries the whole response, so a very long reply arrives in one line** → `STREAM_LINE_MAX_BYTES`
  is 16 MiB, far above a response bounded by the service's output limit; past it, the stream counts as broken.
- **Sending the whole conversation back on every request grows its input** → the token budget counts it (D7), and the
  service's prompt cache (seen in Ollama's recording: 373 of 401 input tokens cached) softens the cost.
- **A host's Responses API differs from OpenAI's** (no usage, no `cache_write_tokens`, other reasoning items, other
  error codes) → each has a defined behaviour (D4, D8, D9), and the Ollama fixture and live test exercise one
  non-OpenAI host.
- **TLS trust on a uv-managed Python** may not find the system's certificates on some machines → `SSL_CERT_FILE` and
  `SSL_CERT_DIR` reach the runner, and the TLS failure's message says to set them.
- **Masking by pattern can miss an echo in a form it doesn't know** → the exact value is always masked; the masked
  form covers the shape OpenAI uses, and the canary scan runs over every fixture.
- **The token budget overshoots by one response** → stated in the result; a response is bounded by the service's own
  output limit.
- **The audition's model goes stale** → it's one named value; the live test names the model it ran.

## Migration Plan

None: a new runner. Nothing existing changes behaviour. Removing it is removing its table entry, its audition and its
package.

## Open Questions

- **The default token budget.** 1,000,000 tokens is a guess at "about what the Claude Code runner's USD 5 allows on a
  small hosted model". The owner may want it lower. It's one named value.
- **Which failed-response codes are the service's own** (`SERVICE_FAILURE_CODES`): `server_error` is certain; the rest
  are listed from OpenAI's error codes when the classifier is written, and a code not listed ends the run, which loses
  nothing.
