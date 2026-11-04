# Design: the OpenAI-style runner

## Context

See proposal.md for why. What the design builds on:

- **The runner contract, version 0** (`protocol/schemas/runner/`, `contributing/runners.md`): JSON-RPC over stdio, one
  run per process, `init` first, `tool_call`/`tool_result` pairs, `retry` with a fixed list of reasons, one `result`
  with optional usage and `costUsd` ("as the engine reports it"), and a transcript of opaque native records.
- **The plugin SDK** (`troupe-plugin-sdk`, #240): the contract's types, `Declaration.from_run_start`, and
  `Tools`, which checks a model's tool call against the declared effects, carries it out and returns the event
  pair and the text for the model. It depends only on the standard library and does no I/O but the workspace.
- **The Claude Code runner** is the pattern to follow: a self-contained plugin with closed options, a `defaults.py`
  holding every limit, published options and error schemas, fixtures that pair real output with expected events,
  a capture tool, and an opt-in live test. It reads stdin on a thread and passes messages over a queue.
- **Runtimes (#278, PR #287)** say where an actor's service comes from: `runtimes.<name>` with an endpoint, a model
  and a credential that is the name of an environment variable, resolved from troupe's built-ins (`openai`,
  `ollama`, `lm-studio`), the theatre's config and the person's environment (`TROUPE_RUNTIME_<NAME>_...`). An actor
  may set its own `model`. troupe refuses a credential over plain HTTP to another machine, one shorter than 8 bytes,
  and an unset variable, all before a run is recorded, and masks the credential in what it stores. That config can
  choose the endpoint, and the variable, is an accepted risk for now, with policy to limit both later (#287's
  design D7; owner, 2026-11-04).
- **Order** (#239, NEXT.md): #56 makes the first round of contract changes; this change's contract changes wait for
  it. The owner chose (2026-11-04) to build this runner on version 0 as it stands and file each gap it finds.

## Goals / Non-Goals

**Goals:**
- A runner that works against OpenAI and against local OpenAI-compatible servers (Ollama's and LM Studio's `/v1`)
  without per-host code.
- Every way a hosted service fails maps to one defined, tested behaviour.
- The credential can't leak into anything troupe keeps, even when the service echoes it.
- The contract's gaps are found and written down precisely, not papered over.

**Non-Goals:**
- Choosing, resolving or validating the runtime (#278), beyond the runner's own defence in depth (D11).
- Estimating cost from a price list (waits on a contract change, D12).
- Parallel tool calls, a shell tool, images, audio, or the Responses API.

## Decisions

### D1. One plugin, `openai-chat`, separate from #56's

The runner is `plugins/runner-openai-chat`, package `troupe-runner-openai-chat`, module `troupe_runner_openai_chat`,
runner name `openai-chat`. The name leaves room for a Responses API runner later without renaming.

It's not an adapter inside #56's local-model plugin, even though Ollama and LM Studio also serve Chat Completions:
#56 deliberately uses each engine's native API, and #239 chose separate plugins so the two runners test the contract
independently. The SDK already shares the code they'd have in common.

### D2. The runtime's hand-off, as #278 gives it

This was assumed before #278 was designed, and checked against PR #287 (task 1.1). The runner gets:

- in `run/start`, `runtime`: `name`, `endpoint` (the base URL; the runner adds `/chat/completions`), `model` (already
  resolved from the person's environment, the actor and the runtime), and `credential`, a boolean;
- when `credential` is true, the value in its environment as `TROUPE_RUNTIME_CREDENTIAL`, read with the SDK's
  `runtime_credential`, which refuses a `run/start` and an environment that disagree
  (`openai-chat.credential-mismatch`).

The runner table gives `openai-chat` `runtime="required"`, so config refuses an actor on it that names no runtime; the
runner still refuses a `run/start` without one (`openai-chat.no-runtime`), from a host that doesn't keep the
contract. The runner touches the runtime in one module (`runtime.py`).

The built-in `ollama` runtime's endpoint is Ollama's own API (`http://127.0.0.1:11434`, for #56's runner), not its
OpenAI-style one under `/v1`. An `openai-chat` actor on it gets a 404, so a 404 without OpenAI's error shape names the
URL it tried and says the endpoint must be the base its Chat Completions API is served under (D8). `lm-studio`'s
built-in endpoint already ends in `/v1`.

Alternatives: endpoint and model in this runner's options (the issue's first wording) was overtaken by the owner's
runtime model, which keeps a service's settings in one place for every runner; reading `OPENAI_API_KEY` directly
would let config choose where a key goes (#160's finding).

### D3. HTTP from the standard library, behind one module

Requests go through `urllib.request` in `service.py`, the only module that does network I/O, with a redirect handler
that refuses every redirect (urllib otherwise follows them and resends the `Authorization` header). urllib also
honours `HTTPS_PROXY` and `NO_PROXY`, and uses the platform's TLS trust store, or `SSL_CERT_FILE`/`SSL_CERT_DIR`.

Alternatives: `httpx` gives nicer timeouts and streaming, but is a dependency every install carries for one module;
the `openai` SDK retries on its own terms, follows its own redirect and header rules, and hides the wire bytes the
transcript has to keep. The SDK and both existing runners depend on nothing outside the standard library and the
SDK, and this keeps it so.

### D4. Streamed responses

Every request sets `"stream": true` and `"stream_options": {"include_usage": true}`. Streaming gives three things a
single response can't: events while the model works (so troupe's silence announcement means something), a stream
timeout that tells a stalled service from a slow one, and the broken-stream case the issue names. The runner reads
server-sent events line by line, takes `data:` lines, stops at `data: [DONE]`, and builds the response from the
deltas of choice 0: text, refusal, reasoning (kept for the transcript), and tool calls accumulated by `index`, the
first delta of each giving its `id` and name and later ones appending to its arguments. Usage comes from the final
chunk, whose `choices` is empty.

A response is complete only when a finish reason has arrived and the stream has ended (`[DONE]` or end of body).
Anything else is a broken stream (D8): its partial tool calls are dropped, never carried out.

A host that rejects `stream_options` answers 400, which ends the run with the service's message (D8). That's
deliberate: without usage the token budget can't work, and the message names the problem.

### D5. Threads and a queue, as the Claude Code runner does

The main thread owns stdout and the protocol. One thread reads stdin and puts messages on a queue. The tool loop runs
on a worker thread, putting events and transcript records on the same queue for the main thread to send, so `seq`
stays ordered and only one thread writes stdout. Each request's response object is held where the main thread can
close it: on `run/cancel` or end of input, the main thread sets a stop flag and closes the connection, which wakes the
worker's blocking read, and the worker sends nothing more. The runner exits within its own named grace, below troupe's
cancel grace, whether or not the worker has finished.

Alternative: asyncio with a thread per request. It's no simpler, and the Claude Code runner's structure is already
tested on all three platforms.

### D6. The tool loop

```
messages = [system(instructions + character?), user(direction)]
for turn in 1..maxTurns:
    response = request(messages)            # retries inside (D8)
    send turn(text) if text
    if refusal / content_filter / length / unknown finish without calls: error result
    if no tool calls: ok result(text); stop
    messages += assistant(text, tool_calls)
    for call in response.tool_calls:        # in order
        step = tools.run(call.id or made-up id, call.name, call.arguments, numbering)
        send step.events; messages += tool(call.id, step.output)
    if tokens used >= maxTotalTokens: error result (budget); stop
error result (turn limit)
```

`Tools.for_declaration(Declaration.from_run_start(params))` makes the tools; `Tools.offered()` gives the
definitions, sent as `{"type": "function", "function": {"name", "description", "parameters"}}` without `strict`,
which not every compatible host accepts. The calls of one response run in order, one at a time: the SDK's tools
share a workspace, and order is what the model asked for. A call with no id gets `call-<n>`, unique in the run.

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

The token budget is checked after each response, so a run can go past it by one response; the result says how far.
Prompt tokens are counted again on every request, since the whole conversation is resent: a long run's input grows
with the square of its turns, which is why the budget counts tokens rather than turns alone.

Options can set `maxTurns` and `maxTotalTokens`, higher or lower than the defaults. Policy limits on runners don't
exist yet; when they do, they bound these.

**Testing never runs on the real-use defaults** (owner, 2026-11-04). The defaults are sized for real work. Every run
made while building and testing sets low limits through the options, from one place in the plugin's tests
(`TEST_LIMITS`: `maxTurns` 5, `maxTotalTokens` 20,000). That covers the runner tests, fixture replays, conformance,
troupe's perform tests and the live test. A runaway loop or a misread finish reason then stops within a few turns,
instead of after 50 turns or a million tokens. Against the fake endpoint that means a fast failure. Against a real
service it means a few cents. A test that needs more (the turn-limit test, say) sets its own values explicitly.
That the defaults apply when no options are given is checked by parsing the options, never by running a real
service on them. Manual tries follow the same rule: the docs' first example sets the same low limits in the actor's
options, and says to raise them once the actor behaves.

### D8. Failures

| What the service does | Retried? | What the run shows |
|---|---|---|
| 401, 403 | no | `error` result: the service refused the credential, with its message |
| 429, error code `insufficient_quota` | no | `error` result: the account is out of quota |
| 429 otherwise | yes | `retry` `rate-limit`, delay `Retry-After` if given, else backoff; past the cap, `error` result |
| 400 with `context_length_exceeded` | no | `error` result: the conversation is longer than the model's context |
| any other 4xx | no | `error` result naming the status and the service's message |
| 404 without OpenAI's error shape | no | `error` result naming the URL tried, and that the endpoint must be the API's base, often ending in `/v1` |
| 3xx | no | `error` result naming the status and `Location` (D3) |
| 5xx | yes | `retry` `server` |
| connection refused, reset, DNS, TLS, connect timeout | yes | `retry` `network` |
| stream silent past `STREAM_TIMEOUT_SECONDS`, ended early, or a line that isn't a valid event | yes | `retry` `network`; the partial response is dropped |
| a refusal, `content_filter` | no | `error` result: refused |
| `length` | no | `error` result: the output limit |

The error body's shape is OpenAI's (`{"error": {"message", "type", "code"}}`). A body that isn't that shape is quoted
as text, cut to the summary limit. Each `retry` event's `attempt` is the attempt that failed, `maxAttempts` is
`MAX_ATTEMPTS`, and `message` is the status and the service's words.

An authentication failure isn't sent as a `retry` with reason `authentication`, since nothing is retried. troupe's
fail-fast on authentication retries is for engines that retry on their own; here the run ends at once anyway. That
the result can't say *why* in a field is gap 1 (D12).

### D9. Usage and cost on contract version 0

Chat Completions' `prompt_tokens` includes the cached tokens in `prompt_tokens_details.cached_tokens`. Anthropic's
`input_tokens`, which the Claude Code runner maps to `inputTokens`, excludes them. So that the four counters mean the
same whichever runner reported them, `inputTokens` is `prompt_tokens − cached_tokens` and `cacheReadTokens` is
`cached_tokens`. `cacheWriteTokens` is absent: Chat Completions doesn't report it. That the contract doesn't say this
itself is gap 3.

`costUsd` is defined as what the engine reports. OpenAI reports no cost, so OpenAI runs have none. Some compatible
hosts (OpenRouter, for one) put a `cost` in usage; the runner sums it when every response has one. A configured price
would give an *estimate*, which version 0 has no field for (gap 2), so the token budget, not a price, bounds spend.

### D10. The transcript's framing

There's no native output to pass through unchanged: the runner itself conducts an HTTP exchange. Each transcript
record is a JSON object of the runner's own, in order:

- `{"kind": "request", "url": ..., "body": "<the body as sent>"}`
- `{"kind": "response", "status": 200, "headers": {...}}`, with only the headers named in `defaults.py`
  (`retry-after`, `x-request-id`, and the `x-ratelimit-*` family)
- `{"kind": "stream", "line": "<one line of the stream, unchanged>"}`
- `{"kind": "body", "body": "<a non-streamed body, such as an error>"}`
- `{"kind": "dropped", "reason": ...}` when a broken stream is abandoned

Bodies and lines are kept as strings, so they're byte-for-byte what crossed the wire, after masking (D11). Request
headers are never recorded. That a runner must invent this framing is gap 4.

### D11. The credential

- The value is read once from the environment variable the runtime names (D2), kept in memory, and put only in the
  `Authorization` header.
- **Masking:** everything the runner sends troupe (events, transcript records, logs, error data) goes through one
  function that replaces the credential, and a masked echo of it, with `[credential]`. A masked echo is a token that
  contains a run of `*` and starts with the credential's first four characters or ends with its last four, which
  covers OpenAI's `sk-proj-****...abcd` form. A credential shorter than eight characters is masked whole only; it's
  too short to match safely by its ends.
- **Defence in depth on the endpoint:** a runtime with a credential and an `http` endpoint to a non-loopback host is
  refused at `run/start` (`openai-chat.insecure-endpoint`), as troupe already refuses it before the run; redirects
  are refused (D3). Which endpoint config may send a credential to is an accepted risk for now (#287's D7).
- **troupe masks too:** it masks the credential in the transcript and everything else it stores (#287). The
  runner's own masking stays, since a log, an error and stderr are also the runner's to keep clean.
- **Tests** run every fixture and failure mode with a canary credential and scan every byte the runner wrote to
  stdout and stderr for it and its masked forms.

### D12. The contract's gaps, found so far

Candidates, each confirmed while building and then filed as its own issue on the board (0.2.0), proposed as its own
change after #56's round, and adopted by this runner then:

1. **A failed result has no reason troupe can act on.** Authentication, quota, rate limit exhausted, context length,
   refusal, output limit, budget and turn limit are all `status: error` with a message. troupe can't tell a person
   "fix your key" from "raise the budget" without parsing text.
2. **No estimated cost.** `costUsd` can only be what the engine reports, so a service that reports no price has no
   cost at all, and a price-list estimate has nowhere to go.
3. **`inputTokens` doesn't say whether it counts cached input.** OpenAI's prompt tokens include it; Anthropic's input
   tokens don't (D9).
4. **Transcript records have no kind.** A runner that drives an API, rather than an engine with its own output,
   invents a framing (D10), and nothing can read two runners' transcripts the same way.
5. **The model served isn't the model asked for.** Each response names the model that answered (often a dated
   version), after `init` has gone; it can only be a `log`.

#56 may find some of these too; filing checks its issues first, so each gap is filed once.

### D13. Testing

- **A fake endpoint** in the plugin's tests: a `ThreadingHTTPServer` on `127.0.0.1` that answers each request from a
  script (a status, headers, a body, or a stream of lines with optional pauses and a cut-off), records every
  request it got with its headers, and can hold a response open. Tests drive the runner as a subprocess, as the
  Claude Code runner's tests do.
- **Fixtures** in `plugins/runner-openai-chat/fixtures/chat-completions/<name>/`: the responses, `expected.json`
  (events and outcome) and `provenance.json` (service, model, date, and recorded, derived or built). Recorded where
  possible: a success with tool calls against a local server (Ollama or LM Studio, no credential) and against
  OpenAI (the owner, a few cents), and a rejected credential from OpenAI with an invalid key (free). A rate limit,
  a server error and a refusal can't be had on demand, so they're built from OpenAI's documented shapes; the broken
  stream is a recorded success cut short.
- **A capture tool**, `tools/capture_openai_chat.py`, records a fixture's responses and writes its provenance, and
  scrubs the credential and the capturing host's paths.
- **Conformance:** `check_runner` with the runner pointed at the fake endpoint, which answers every request with a
  short `stop` reply.
- **The live test**, `TROUPE_LIVE_OPENAI_CHAT=1`, with the runtime taken from the person's environment, a model pinned
  in the test, and `TEST_LIMITS` (D7). Pointed at a local server, it costs nothing.
- **Property tests** for the stream parser (arbitrary chunking of a recorded stream gives the same response) and the
  masking function (no output contains the credential, whatever surrounds it).

### D14. Shipping it

The runner joins the `uv` workspace, the typing and lint paths, the import contracts (`plugins import nothing from
troupe`, `plugins are independent of each other`, and an I/O seam contract naming `service.py` like the Claude Code
runner's `processes.py`), `scripts/check-paths.toml`, release-please's config and manifest, and the `troupe-run`
bundle's pins, each as the Claude Code runner was added. `troupe.core.interim.RUNNERS` gains `openai-chat` with its
environment: the proxy variables, `SSL_CERT_FILE` and `SSL_CERT_DIR`, and on Windows what Python needs to start
(`SYSTEMROOT` comes from the platform minimum), and `runtime="required"`. troupe adds `TROUPE_RUNTIME_CREDENTIAL`
itself when the runtime has a credential (#287).

## Risks / Trade-offs

- **#278's shape differed from D2** → checked against PR #287 (task 1.1); it didn't, beyond the details now in D2.
- **A compatible host differs from OpenAI** (no `stream_options`, tool calls without ids, no usage, odd finish
  reasons, error bodies of another shape) → each has a defined behaviour (D4, D6, D8, the usage requirement), and the
  local-server fixture and live test exercise one non-OpenAI host.
- **TLS trust on a uv-managed Python** may not find the system's certificates on some machines → `SSL_CERT_FILE` and
  `SSL_CERT_DIR` reach the runner, and the TLS failure's message says to set them. The live test checks it on the
  owner's machine.
- **Masking by pattern can miss an echo in a form it doesn't know** → the exact value is always masked; the masked
  form covers the shape OpenAI uses, and the canary scan runs over every fixture.
- **The token budget overshoots by one response** → stated in the result; a response is bounded by the service's own
  output limit.
- **A long run's cost grows with the square of its turns** → the token budget counts it; the default is a guess (Open
  Questions).
- **The bundle's pin for a component that's never been released** → follow how `troupe-runner-claude-code` was added,
  and #262's check that refuses a bundle release with an unpinned member.

## Migration Plan

None: a new runner. Nothing existing changes behaviour. Removing it is removing its table entry and its package.

## Open Questions

- **The default token budget.** 1,000,000 tokens is a guess at "about what the Claude Code runner's USD 5 allows on a
  small hosted model". The owner may want it lower. It's one named value.
- **The live test's pinned model** is chosen when the test is written, from the service's current small models.
