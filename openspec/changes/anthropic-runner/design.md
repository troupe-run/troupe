# Design: the Anthropic Messages API runner

## Context

- **Three loop runners drive troupe's own tools today.** Ollama (`runner-ollama`, its native API by hand), OpenAI
  (`runner-openai`, the Responses API by hand over the standard library) and LM Studio (`runner-lm-studio`, through the
  `lmstudio` package, the first library-backed runner, which #413 removes). Each checks every call against the actor's
  declared effects through the plugin SDK (`init` says `checked`). The OpenAI runner is the nearest model for the loop
  (one conversation the runner holds and resends, streamed replies, retries in its own loop, compaction on a
  context-length refusal). The LM Studio runner is the nearest model for shipping a library (#319's guarantees, #333's
  extra, the licence check, a seam module that alone imports the library).
- **The contract** (runner-protocol) already has everything this runner needs: runtimes with a credential by reference
  (#278), `reason` on error results (#296), estimated cost (#292), transcript kinds (#294), `served_model` (#295),
  `notRetried` (#378), `onContextFull` and the `context` event (#307, #310, #328).
- **`anthropic` 2.8.0** (Apache-2.0, Python ≥ 3.10; released 2026-11-10, after a release roughly weekly since
  2.3.0 on 2026-10-23), read from its source on 2026-11-14:
  - built on `httpx2`; depends on `anyio`, `docstring-parser`, `httpx2`, `jiter`, `opentelemetry-api`, `pydantic`,
    `sniffio` and `typing-extensions`;
  - **follows redirects by default** (`follow_redirects=True` on the client it builds), and **retries** 408, 409, 429,
    5xx and connection errors twice by default, honouring `retry-after-ms`, `retry-after` and `x-should-retry`;
  - with no explicit credential argument it **discovers one**: `ANTHROPIC_API_KEY`, then `ANTHROPIC_AUTH_TOKEN`, then
    `ANTHROPIC_PROFILE`, workload identity variables, and the active profile on disk. An explicit `api_key=` (or a
    subclass of the client) turns discovery off. It also reads `ANTHROPIC_BASE_URL`, `ANTHROPIC_CUSTOM_HEADERS` and
    `ANTHROPIC_LOG`, and can emit OpenTelemetry spans;
  - sends an `api_key` as `Authorization: Bearer <key>`;
  - its default timeout is ten minutes.
- **The probe** (D12; findings on troupe#415, issuecomment-6865689324): LM Studio and Ollama both serve the Messages
  API with working tool calls; both cut a conversation that outgrows their window and answer `200`; LM Studio refuses
  a first prompt over the window with a `500`; and the two disagree on what `input_tokens` counts.

## Goals / Non-Goals

**Goals:**

- An `anthropic` runner that passes the conformance suite and is proved against LM Studio and Claude's API with
  recorded fixtures.
- Each of #319's guarantees kept by the runner, each pinned by a test against the fake endpoint, not left to the
  library's defaults, which break three of them (redirects, retries, credential discovery).
- #279's rule kept against engines that break it silently: no reply made from a cut conversation is acted on.
- Each gap found in the contract, the library or an engine filed as its own issue (D13).

**Non-Goals:**

- Claude-only features: server tools, the SDK's tool runner, server-side compaction, message threads, prompt-caching
  controls, refusal fallbacks, batches, structured outputs. The runner speaks the subset every engine serves (D2).
- Choosing thinking or effort settings. The model's default applies, and thinking blocks are sent back unchanged.
- The Bedrock, Vertex and Foundry clients, and an `x-api-key` header (D4).
- Removing the LM Studio runner and its built-in `lm-studio` runtime, which is #413's job (D3).

## Decisions

### D1. `anthropic`, pinned, behind one seam module

The runner depends on `troupe-plugin-sdk` and `anthropic==2.8.0`. One module, `service.py`, imports `anthropic` and
`httpx2`; everything else works with the runner's own types (a request's parameters as a dict, a reply as the
library's message serialised to a dict, and a closed set of failures), so a library bump touches one module and the
fixtures catch what it changes. An import contract pins the seam, as the LM Studio runner's does.

**Alternatives:** the standard library by hand, as the OpenAI runner does. #319 prefers a maintained library ("don't
talk raw HTTP when we can use … a library"), and #412 names this package. The async client: the runner's threads
(D9) already work with the sync client, and the LM Studio runner showed the threading model holds.

### D2. troupe's own loop, over the subset of the API every engine serves

The runner holds the conversation and sends it whole each request (`system`, `messages`, `tools`, `max_tokens`,
`model`, `stream`), as the OpenAI runner does, and nothing else. It doesn't use the SDK's tool runner
(`client.beta.messages.tool_runner`): that's a beta helper that decides when the loop ends, would hide the requests
the transcript must keep, and has no place for troupe's turn limit, budget or context guard. Each reply's content is
appended unchanged as the assistant message, so `thinking` blocks and their signatures go back as the service gave
them, which Claude's current models require.

Tools are the SDK's definitions as custom tools (`name`, `description`, `input_schema`), not `strict`: Claude's strict
mode requires every property in `required`, which the SDK's optional fields aren't, and local engines ignore it. A
`tool_use` block's `input` is checked by the SDK when the call runs, as for the other loop runners. Calls run one at a
time in the reply's order, and their results go back in **one** user message, which the API expects (results split
across messages make Claude stop calling tools in parallel).

`tool_choice` isn't sent, so it's `auto`: Claude's current models refuse a forced choice.

### D3. Runtimes: a built-in for Claude, a runtime of your own for a local engine

- **The endpoint is the API's base URL.** The library adds `/v1/messages`. Claude's is `https://api.anthropic.com`,
  and LM Studio's, Ollama's, llama.cpp's and LocalAI's are their server roots. A path is allowed, since gateways serve
  the API under one (`https://gateway.example/anthropic`), but a path ending in `/v1` is refused
  (`anthropic.unsupported-endpoint`), naming the base without it: it's the OpenAI-style base copied across, and would
  send requests to `/v1/v1/messages`. A query or fragment is refused too, since the library would drop or garble it.
  Refusing is the rule for an input that can't be used as given; stripping `/v1` would be guessing.
- **A new built-in, `anthropic`**: `https://api.anthropic.com`, credential from `ANTHROPIC_API_KEY`, no model and no
  price, as every built-in. The runner table gives the runner `runtime="required"`, `in_extra=True` and
  `fit=RuntimeFit(built_in="anthropic")` (path `any`, a credential allowed, any scheme). Its environment is the
  same proxy variables the OpenAI runner gets (`OPENAI_ENVIRONMENT`), since the library's HTTP client reads them as
  `urllib` does; nothing else reaches it, so none of the `ANTHROPIC_*` variables do (D4 defends against them anyway).
- **A local engine is a runtime the person defines**: for LM Studio, `troupe config set
  runtimes.lm-studio-messages.endpoint=http://127.0.0.1:1234` and `troupe config set
  actors.<name>.runtime=lm-studio-messages`. This change neither keeps nor re-points the built-in `lm-studio` runtime:
  it fits only the LM Studio runner (lmstudio-runner design D3), and #413 removes both (owner decision, 2026-11-14,
  option 2 of the three raised: re-point it to this runner, remove it, or let it fit both). No built-in serves a local
  Messages API engine, so the docs and the README show the two lines, and a spec scenario pins that such a runtime
  reaches the engine.

### D4. The credential, and nothing the library finds for itself

- The credential is read from `TROUPE_RUNTIME_CREDENTIAL` only when `run/start` says there is one, checked as the
  OpenAI runner checks it (mismatch, malformed), and refused over plain `http` to a host that isn't loopback.
- It's passed to the library as `api_key=`, which the library sends as `Authorization: Bearer <key>`. Claude's API
  accepts that (the library's own default for API keys), and LM Studio's token and most gateways read `Authorization`
  too. `x-api-key`, Claude's older header, isn't sent; an engine that only reads it is a gap to file, not to guess at.
- **With no credential, the library must find none.** Passing nothing makes it read the environment and the profile on
  disk, which could send the person's own Claude token to a local engine. So the client is built by a subclass of the
  library's client (`_RunnerClient`), which the library treats as having its own auth and never runs discovery for,
  with `Authorization` explicitly omitted. The runner also passes `base_url`, `default_headers` and `http_client`
  itself, so `ANTHROPIC_BASE_URL` and `ANTHROPIC_CUSTOM_HEADERS` change nothing. Perform starts the runner without
  those variables (D3), and a test starts it with them set, and with a profile under `ANTHROPIC_CONFIG_DIR`, to show
  they change nothing (spec: "The library finds nothing of its own").
- Masking: everything the runner sends troupe passes through the SDK's credential masking (whole value, and the
  `prefix****suffix` echo services use), as the OpenAI runner's does, error text and the transcript included.

### D5. Options and limits, each default named once

The options are closed: `maxTurns` (default 20), `maxTotalTokens` (default 200,000), `maxOutputTokens` (default
16,000, sent as `max_tokens`, which the API requires) and `contextWindow` (no default). The defaults live in the
runner's `defaults.py`, with the library's timeouts (D10), the retry count and backoff, the `Retry-After` cap, the
stream timeout, the cancel grace, the compaction share (D11) and the summary limit.

`maxOutputTokens`' default is the API's recommendation for non-streamed requests, so a local engine with a small
window isn't asked for more than it has (LM Studio's 8,192 took `max_tokens` 512 and 5 in the probe; whether it
refuses a `max_tokens` above its window is a probe item, D12). The audition sets nothing beyond `maxTurns` and
`maxTotalTokens`, as the OpenAI audition does.

`contextWindow` is the engine's context window when the person knows it (D8). It's an option, not a runtime field,
because it belongs to a model on an engine, and a runtime may serve several models; an actor names one model.

### D6. The pre-run check

Before answering `run/start` the runner checks, in order: the runtime is present (`anthropic.no-runtime`), the
endpoint can be used (D3), the credential (D4), and the options. It makes no request before acknowledging: a request
costs money on Claude's API, and an unreachable service shows as a failed first request, retried as `network` and
then ended with that reason, as the OpenAI runner's does.

### D7. Mapping replies to events and results

- **A reply's stream** is read through the library's stream, which gives each server-sent event as a parsed object
  and the accumulated message at the end. Each event goes to the transcript as it arrives (D11). Nothing is acted on
  until `message_stop`: a stream cut short is dropped whole (spec: broken stream).
- **Text** is the reply's `text` blocks, joined, one `turn` before its tool calls. `thinking` and `redacted_thinking`
  stay in the transcript. A model whose reasoning arrives inside its text (the probe's Gemma on LM Studio wrote it
  before `<channel|>`) shows it in the turn: the runner doesn't parse model-specific markers, and the README says so.
- **`stop_reason`**: `tool_use` carries out the calls; `end_turn` and `stop_sequence` end `ok`; `max_tokens`
  `output-limit` (no call from the reply runs, since its last block may be cut); `refusal` `refused`, with
  `stop_details` in the message; `model_context_window_exceeded` `context-length`; `pause_turn`, which only server
  tools cause, and any other value `engine`, naming it. A `tool_use` stop with no `tool_use` block is `engine`.
- **Usage** is the Messages API's definition: `input_tokens` excludes the cache counters. Each reply's counters go
  into the result as the OpenAI runner sums them, a cache counter only when every reply reports it, and the budget
  counts all four. LM Studio counts cache reads inside `input_tokens` (probe), so its runs over-report input by the
  cache reads; that's an engine bug, filed upstream (D13), not a guess the runner makes per engine.
- **Cost:** the API reports none, so there's never `costUsd`; `estimatedCostUsd` comes from the run's price through
  the SDK's estimator, as for the other runners, which leaves it out when a cache counter has no price.
- **`served_model`:** each reply's `model`, when it isn't the runtime's, once per model, before its events.

### D8. The context guard: never act on a reply made from a cut conversation

#279 and the contract say a run told `fail` ends with `context-length` when its context fills, and that neither the
runner nor its engine may drop content silently. The probe found that both local engines do exactly that through the
Messages API, with no request parameter to stop them, and LM Studio's refusal of an over-long first prompt is a `500`
that would otherwise be retried as a server error. So the runner guards three ways, each judged in one place
(`context.py`):

1. **Signals.** One table maps each engine's context refusal to `context-length`: Claude's `400`
   `invalid_request_error` "prompt is too long", LM Studio's `500` "greater than the context length", and llama.cpp's
   `exceed_context_size_error` (from its documentation, marked as such until a probe or a fixture confirms it), and
   `stop_reason` `model_context_window_exceeded`. Matching a message is fragile, so each entry names its engine and
   the fixture that pins it, and a signal the table doesn't know falls to the general rules: a `500` is retried and
   ends `server`, which is loud, not silent.
2. **A shrinking prompt.** A request's prompt is its reported `input_tokens + cache_read_input_tokens +
   cache_creation_input_tokens`. The conversation only grows, since every request is the previous one plus the
   reply and the results, so a prompt smaller than the previous request's means the engine answered from less than
   it was sent. That reply isn't acted on: no turn, no tool call. Both of the probe's silent cuts are caught this way.
   A template that renders earlier turns smaller (some drop past reasoning) could in principle shrink a prompt without
   loss; failing then is the conservative side, and the message says what was compared.
3. **The window the person named.** With `contextWindow` set, a reply whose prompt and output reach it is acted on (it
   was made from the whole conversation), and no further request is sent; a reply whose prompt alone reaches it isn't
   acted on, since an engine at its window may already have cut.

**What it can't catch:** a first request already over the window on an engine that cuts it silently (Ollama, in the
probe). There's no earlier prompt to compare with, and counting tokens needs the model's tokenizer. The README says
so, names the engines the runner is proved against, and recommends `contextWindow`. Claude's API and LM Studio refuse
that case, so neither is affected.

**Alternatives:** count tokens with `count_tokens` before each request: Claude's API serves it, but local engines
don't, and it doubles the requests. Estimate from bytes: a byte count can't bound a token count in either direction
for every tokenizer. Leave it to the engine: that's the silent loss #279 rules out.

### D9. Threads and stopping

As the OpenAI runner: the main thread reads troupe's messages and answers them; after `run/start` is acknowledged a
worker thread sends `init` and runs the loop; every line goes to standard output whole under one lock. Stopping
(`run/cancel`, end of input, `shutdown`) sets a flag under the lock, so no event follows the acknowledgement, and the
loop checks it before each tool call and each request. The request in flight is abandoned by closing the library's
stream and the runner's own HTTP client from the main thread, which closes the connection; the probe (D12) confirms
the library's stream raises at once when that happens mid-read. The runner exits within its own named grace, below
troupe's, whether or not the worker has finished, ending the process from its exit path if it must.

### D10. Retries, redirects and timeouts

- **Retries** are the runner's: the library gets `max_retries=0`. The loop retries 429, 5xx (529 `overloaded_error`
  included), a stream `error` event of type `overloaded_error` or `api_error`, network errors, timeouts and broken
  streams, within its named attempts and backoff, honouring `retry-after-ms` and `Retry-After`, a 429 asking longer
  than the cap ending `rate-limit`. Every request is the whole conversation and tools run only after a whole reply,
  so a retry never runs a tool twice and `notRetried` is never needed. A context signal (D8) is never retried.
- **Redirects** aren't followed: the runner builds the library's `httpx2` client itself with
  `follow_redirects=False` (the library's own default client follows them), so a 3xx reaches the runner as a status
  error, which ends `configuration` naming the status and location. A test pins that nothing connects to the
  location.
- **Timeouts:** the runner's client gets connect, read, write and pool timeouts from named settings, and the library's
  `timeout` is the same object, so the ten-minute default never applies. The read timeout is the stream timeout: a
  stream that sends nothing for that long is abandoned as `network`. Claude's API sends `ping` events through a long
  reply, so a slow but live stream isn't a timeout.
- **#333's guarantees,** as `contributing/runners.md` "Runners with client libraries" lists them: retries and timeouts
  as above; no redirect and the credential only in its header (D4); cancel within the grace (D9); the transcript as the
  library exposes it (D11); pinned dependencies on the licence list, any MPL-2.0 one from PyPI only (D15).

### D11. The transcript, and compaction

- **Transcript:** each request's parameters as passed to the library (`sent`); each stream event the library parses,
  as its `to_dict()`, and each error body (`received`); and a `note` for each response's status with the headers named
  in one place (`request-id`, `retry-after`, `retry-after-ms`, the rate-limit headers, `content-type`), and each stream
  abandoned. **Compared with the wire** it loses the SSE framing (`event:` lines, blank lines, comments), any event the
  library reads and drops, and unknown fields the library's models don't keep (they keep extra fields today, and a
  fixture test pins a field the runner doesn't read surviving). Request headers are never recorded.
- **Compaction** (a run told `compact`): on a context signal, a shrinking prompt or the window (D8), the runner stubs
  old `tool_result` contents through the SDK's `compaction` helpers (`Candidate`, `stub`, `choose`), oldest first,
  until its byte estimate is at or below a named share of the last whole request's prompt, then sends a `context`
  event (`truncated`, `by: runner`, with `messagesBefore`/`messagesAfter`) and the request again, not counted as a
  turn. It never touches the `system`, the first user message, any assistant message (thinking and tool-use blocks
  must go back unchanged) or the latest turn's results. Nothing left to stub ends `context-length`, saying compaction
  was on. It's the OpenAI runner's rule on this API's shape. Claude's own server-side compaction isn't used: local
  engines don't serve it.

### D12. A probe first, and fixtures from it

The library's source and the API's documentation left gaps, so the work starts with probes, from the scratchpad and
never committed:

- **Done (2026-11-14):** tool calls and stream events on LM Studio and Ollama, the context limit on both, the output
  limit, the usage counters, and the library's redirect, retry and credential behaviour from its source. Findings on
  troupe#415. **LM Studio is the local engine** this runner is proved against: it was already the owner's engine for
  troupe's local runs, it refuses an over-long first prompt (Ollama cuts that silently), its small loaded window makes
  context fixtures cheap to record, and #413's removal of its own runner leaves this one as the way troupe reaches it.
  Ollama is documented as working, without fixtures.
- **Still to probe before the code that depends on each:** cancel mid-stream from another thread (D9); a 3xx through
  the runner's client (D10); `max_tokens` above LM Studio's window; LM Studio with "Require Authentication" on and a
  Bearer token (D4); the subclass that turns off credential discovery (D4).
- **Claude's API needs the owner's key.** The capture tool runs the cases that need it (a tool loop, a context
  refusal from a long prompt, a refusal if one can be had); the owner runs it with `!` and the key in their own
  environment, and the tool never writes the key. A rejected credential is captured with a deliberately invalid key,
  which needs no key at all.

Recorded runs go in `fixtures/` with provenance (the engine and its version, the library's version, the model, the
date, and recorded, derived or built). The capture tool (`tools/capture_anthropic.py`) drives the library with a
recording transport and writes the request parameters and the streamed events, scrubbing credentials, request ids and
host paths.

### D13. Gaps, found so far

1. **LM Studio counts cache reads in `input_tokens`** (D7). File on LM Studio's tracker, linked from a troupe issue.
2. **Both local engines cut an over-long conversation silently through the Messages API** (D8). File upstream for
   each (LM Studio: a way to choose `stopAtLimit`; Ollama: an error instead of truncation), linked from a troupe
   issue that tracks dropping guard 2 once they're fixed.
3. **The first request isn't guarded on an engine that cuts silently** (D8). Recorded in the README and in the issue
   above, not filed separately.
4. **No `x-api-key`** (D4), filed only if building finds an engine that needs it.

Each is filed as its own issue on the board once building confirms it, checking #279's, #319's and #412's issues
first.

### D14. Testing

- **A fake Messages endpoint** (`tests/fake_messages.py`): an HTTP server on loopback that answers `/v1/messages` with
  scripted or recorded SSE streams and error bodies, and can redirect, drop the connection, stall, send an `error`
  event, answer JSON instead of a stream, or hold a stream open. It records every request with its headers.
- **Fixtures** replayed through it, each with its expected events and outcome.
- **Unit tests** at the seam: the request built from a conversation, the tool definitions against the SDK's, the
  failure table, the context guard's three rules (with a property test that a growing prompt never trips guard 2),
  the options parser against its published schema (a property test).
- **Conformance:** `check_runner`, given a runtime on the fake endpoint.
- **Live tests:** `TROUPE_LIVE_ANTHROPIC=1` against Claude's API (the runtime from the person's environment, the
  audition model, low limits; the owner runs it) and `TROUPE_LIVE_ANTHROPIC_LOCAL=1` against a local engine (the
  runtime and model from the environment; the agent can run it against LM Studio, which costs nothing).
- Every test runs on Linux, macOS and Windows, on every supported Python.

### D15. Shipping it

The runner joins everything the LM Studio runner joined: the `uv` workspace, the typing and lint paths, the import
contracts (and the seam contract, D1), `scripts/check.py`'s scopes (`runner_anthropic`) and `check-paths.toml`,
release-please's config and manifest, the changelog page, and `troupe-run`'s extras as `anthropic` and in `all`, never
the base install. An actor on it without the extra gets #333's error naming `troupe-run[anthropic]`.

**Dependencies.** Before locking, every package `anthropic` pulls in is checked against `scripts/licences.toml` and for
wheels or pure Python on Linux, macOS and Windows for Python 3.12 to 3.15. `pydantic-core` and `jiter` are compiled,
so their wheels for cp315 on each platform are checked first. Anything that fails either check is raised with the
owner before it's locked.

**The audition** names its model in one place (`ANTHROPIC_AUDITION_MODEL`): `claude-haiku-5-5`, Claude's cheapest
current model, as the OpenAI audition names OpenAI's cheapest, with `maxTurns` 10 and `maxTotalTokens` 100,000.
`init` prints the extra to install, that the key goes in `ANTHROPIC_API_KEY`, and that a run costs money within the
budget.

The spec `anthropic-runner` is new, so its Purpose goes into troupe-run/infrastructure's
`oob/troupe-spec-purposes.json`, in a pull request that merges right after this one (troupe first).

**#413 runs alongside.** It edits the same requirements (the runner list in `cli` and `quality-check`, the built-ins
in `runtimes`), the same runner table, docs and extras. Whichever merges second rebases and carries the other's
wording, re-archiving if the archive commit conflicts. This change's `runtimes` delta lists `lm-studio` only because
main still has it; if #413 merges first, the delta drops it, and nothing here depends on it.

## Risks / Trade-offs

- **A library that changes weekly.** `anthropic` released six versions in three weeks. → Pinned exactly; the seam
  (D1), the fixtures and the request-shape tests catch a change in what's sent or read; a bump is its own change, rerun
  against both live tests.
- **The library's defaults break three guarantees** (redirects, retries, credential discovery). → Each is set by the
  runner and pinned by a test that would fail on the library's default.
- **Guard 2 is a heuristic about engines' token counts.** → It errs towards failing, says what it compared, and the
  owner can see every case in the transcript; an engine whose counts shrink without loss is filed, not special-cased.
- **The first request on a silently cutting engine** (D8). → Documented, with `contextWindow` recommended, and the
  upstream issues filed.
- **Matching engines' error messages** for context signals. → One table, each entry pinned by a recorded fixture, and
  an unknown message ends loudly (`server`), never silently.
- **A local engine's model may leak its reasoning into text** (Gemma on LM Studio). → Shown as is; the README says so.
- **Claude fixtures need the owner.** → The capture tool is a script the owner runs; everything else is captured
  without a key, and the PR isn't marked ready without the owner's capture or the owner's word to go without it.
- **Concurrent work on #413** touches the same files. → D15's order; the owner settled the built-in (D3).
