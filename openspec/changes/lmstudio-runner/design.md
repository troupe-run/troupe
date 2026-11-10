# Design: the LM Studio runner

## Context

- **The runner port** is contract version 0 (`protocol/schemas/runner/`, `contributing/runners.md`). Three engines
  are behind it: Claude Code (its own loop and tools), Ollama (#277) and OpenAI (#162). The last two drive troupe's
  own tool loop through the plugin SDK (#239, #240), and each checks every call against the actor's declared effects
  (#241, `init` says `checked`).
- **Runtimes** (#278) name a service once: an endpoint, an optional model and an optional credential by reference,
  resolved from defaults, the theatre's config and the person's environment. `run/start` carries the resolved
  `runtime`. The OpenAI runner is the one runner built on them so far, and Ollama moves next (#289).
- **How this change got here.** It was first proposed on LM Studio's REST API, `POST /api/v1/chat`, which takes no
  custom tools, only MCP servers. #302's probe (LM Studio 0.4.28, 2026-11-07) found that LM Studio refuses any MCP
  server on this machine: "URL resolves to a non-public address. We only allow public addresses for dynamic remote MCP
  connections." #302 is on hold. Decision #319 (owner, 2026-11-07) then let runners depend on maintained client
  libraries, kept to troupe's guarantees by the runner, and installed as optional extras (#333).
- **`lmstudio` 1.5.0** (MIT, Python ≥ 3.10; it depends on httpx, httpx-ws, msgspec, anyio and typing-extensions),
  read from its wheel's source on 2026-11-07:
  - `Client(api_host)` takes `"host:port"`. Without it, the client probes five default ports (41343, 52993, 16141,
    39414, 22931) on 127.0.0.1. It checks the host with `GET http://<host>/lmstudio-greeting`, then opens websocket
    sessions at `ws://<host>/<namespace>`. There's no `wss://` and no TLS option.
  - Its websocket handshake sends `authVersion`, a `clientIdentifier` and a `clientPasskey` it makes up itself (its
    comment: "a cooperative resource management mechanism", not security). **It has no way to send an LM Studio API
    token.**
  - `client.list_downloaded_models()` gives each model's info, an LLM's including `trainedForToolUse` and
    `maxContextLength`. `downloaded.model(config=...)`/`client.llm.model(key, config=...)` gets the model, loading
    it with the given load config (such as `contextLength`) only when it isn't loaded. Its docstring says "configuration
    of retrieved model is NOT checked against the given config". The handle's `get_info()` gives what's loaded.
  - `llm.act(chat, tools, max_prediction_rounds=, max_parallel_tool_calls=1, config=, on_message=,
    on_prediction_fragment=, on_round_start=, on_round_end=, on_prediction_completed=, on_prompt_processing_progress=,
    handle_invalid_tool_request=)` runs the loop on the client's side. Each round is one prediction. Tool calls are
    carried out by calling the tool's Python function in a thread pool (one at a time by default), and their results
    go into the chat for the next round. When `max_prediction_rounds` is set, the last round is sent without tools.
    `on_prediction_completed` gets each round's result, with `stats` (`promptTokensCount`, `predictedTokensCount`,
    `totalTokensCount`, `stopReason`: `eosFound`, `toolCalls`, `maxPredictedTokensReached`, `contextLengthReached`,
    `modelUnloaded`, `userStopped`, `failed` and others). Exceptions raised in callbacks are logged and swallowed.
  - A tool is a `ToolFunctionDef(name, description, parameters, implementation)`, where `parameters` maps each name to
    a Python type (or `{"type": ..., "default": ...}`). The library builds a msgspec struct from it, sends LM Studio
    that struct's JSON schema, and converts each call's arguments with it before calling the implementation. A call
    whose tool doesn't exist, or whose arguments don't convert, goes to `handle_invalid_tool_request(error, request)`,
    whose returned text is sent to the model as the result. **Argument names the struct doesn't define are dropped
    without error.** A result is sent as `json.dumps(return_value)`.
  - The library makes no retries of its own. Its HTTP client is httpx's, which doesn't follow redirects unless asked.

## Goals / Non-Goals

**Goals:**

- An `lm-studio` runner that runs an actor on a model in LM Studio through `lmstudio`, with troupe carrying out and
  checking every tool call, and that passes the conformance suite.
- The service from the actor's runtime, from the first commit: no endpoint or model in the options.
- Every guarantee #319 lists, kept by the runner and each pinned by a test, not left to the library.
- No behaviour that depends on an unverified guess about LM Studio or the library. A probe comes before the code that
  depends on it (D12).
- Each gap in the runner contract or the library filed as its own issue, not worked around (D13).

**Non-Goals:**

- LM Studio's REST API, its OpenAI-compatible and Anthropic-compatible endpoints, and MCP (#302, on hold).
- An LM Studio API token (D4), TLS to LM Studio, starting its server, or downloading models.
- How extras work for every runner (#333), and moving other runners onto libraries (#331, #332).

## Decisions

### D1. `lmstudio`, and the library's own tool loop

The run is one `llm.act()` call. The library decides when a round ends. troupe carries out every tool call, because
each tool's implementation is a function the runner gives the library, which calls the SDK's `Tools.run`. So the
runner's `init` can say `effects: checked`, as the other two loop runners do, and no MCP server is needed.

**Alternatives:** the REST API with an MCP server on this machine, which LM Studio refuses (#302). Writing the SDK's
websocket protocol by hand, which #319 rejects ("don't talk raw HTTP when we can use … a library"). `respond()` with
troupe's own loop: `respond()` takes no tools, and `act()` is the library's only tool-calling API.

### D2. Its own plugin, `lm-studio`, named after its runtime

`plugins/runner-lm-studio`, package `troupe-runner-lm-studio`, module `troupe_runner_lm_studio`, error codes
`lm-studio.*`. An actor reads `runner: lm-studio`, `runtime: lm-studio`, as the OpenAI runner's reads `runner: openai`,
`runtime: openai`. It isn't an adapter beside Ollama's, which moves onto its own library (#332).

### D3. The `lm-studio` runtime is LM Studio's server root

`defaults.RUNTIMES["lm-studio"]` becomes `{"endpoint": "http://127.0.0.1:1234"}`, and the runner gives the library
`127.0.0.1:1234`. The old value, `/v1`, was the base of LM Studio's OpenAI-compatible API, chosen for #162's runner.
The owner chose to repoint it rather than keep a built-in for that API (2026-11-07). The OpenAI runner on LM Studio
still works, on a runtime the person defines at `/v1`, and `docs/stagecraft/runtimes.md` says how.

The runner always passes the host and port, so the library never probes its default ports: a run goes to the service
its runtime names or nowhere. An endpoint with a path or `https` is refused (`lm-studio.unsupported-endpoint`). A
runtime still at `/v1` fails at once, naming the root to use, and `https` can't be honoured because the library speaks
only `ws://`. Refusing is the rule for an input that can't be used as given, and stripping the path or downgrading the
scheme would be guessing.

The runner table gives `lm-studio` `runtime="required"`, no environment (httpx reads proxy variables, so passing none
keeps a proxy from routing LM Studio's traffic), and the extra it's installed by (D15).

### D4. No API token until the library can send one

`lmstudio` 1.5.0 can't send an LM Studio API token (Context). A runtime with a credential is refused
(`lm-studio.credential-unsupported`) rather than run without its token, which would either fail later with a less
clear error or, worse, succeed against an LM Studio that doesn't need it, while the person believes it's protected.
The fix says to turn off "Require Authentication" or remove the runtime's credential. The probe (D12) records what
LM Studio does to an SDK client when authentication is on. A library that can send a token is filed upstream and
adopted when it lands (D13).

Because no credential ever reaches the runner, #319's "the credential goes only in its header and is never logged"
holds trivially. A test still pins that a credential in the environment is refused without its value in any output.

Remote LM Studio isn't refused. Without a credential there's nothing to protect in transit, and runtimes already
refuse a credential over plain HTTP to another host. The traffic is plain `ws://`, and the README says so.

### D5. Options and limits, each default named once

The options are closed: `maxTurns` (default 20), `maxTotalTokens` (default 200,000), `contextLength` (default 16,384)
and `temperature` (unset, so the model's own default applies). The defaults live in the runner's `defaults.py`, as do
the pre-run check's time limit, the library's message timeout, the retry count and backoff, and the cancel grace.

- **The turn limit** is `max_prediction_rounds`. The library sends the last round without tools. The probe found that a
  model still working then may write a raw tool call into its text (`<|tool_call>call:Grep{…}<tool_call|>`), ending
  `eosFound`, without `handle_invalid_tool_request` being called. So the runner detects the limit by count: when
  `act()` used every round and the round before the last asked for tools, the run ends with an `error` result saying
  the turn limit was reached, as the OpenAI runner's spec says, whatever the last round's text says.
- **The token budget** is added up in `on_prediction_completed`, from each round's stats, and enforced in
  `on_round_end`, which the library calls only after that round's tool calls have finished (calls can still be running
  when the round's prediction completes). When it's spent, the runner stops the run (D9) before another round starts,
  so a budget hit never cuts a call short. Callbacks can't stop `act()` (their exceptions are swallowed), so stopping
  means closing the client, as cancel does.
- **`contextLength`** is the load config's, used only when the model isn't loaded (Context). When it's already loaded
  with another length, the run uses it as it is and reports the length in a `log` event. Unloading a model someone
  else may be using, to reload it, isn't the runner's call.

### D6. The pre-run check

Before answering `run/start`, the runner checks, in order: the runtime is present (`lm-studio.no-runtime`), the
endpoint is usable (D3), there's no credential (D4), and the options parse. Then, within a named time limit, it opens
the client with the runtime's host and port and lists the downloaded models:

- no answer, or anything other than LM Studio's greeting, gives `lm-studio.unreachable`, whose fix names
  `lms server start`;
- LM Studio answering its greeting while listing the models fails gives `lm-studio.incompatible`, whose fix names the
  version in the published requirements (`requirements.json`, as the Ollama runner publishes its own). The probe found
  that nothing reports LM Studio's version (not the library, the greeting or the model listing), and lmstudio-python
  states no minimum. So the published version is the one tested (0.4.28), and there's no version check before a run;
- no downloaded LLM whose key is the run's model gives `lm-studio.model-not-found`, whose fix names `lms get <model>`;
- a model not trained for tool use gives `lm-studio.model-without-tools`.

The model is loaded after `init`, not in the check, because loading can take minutes. The library's load progress is
reported as `log` events, so troupe's silence announcement doesn't fire on a long load.

### D7. The chat and the tools

The chat is a system prompt (the runner's fixed instructions, then the character when there is one, as the other
loop runners build theirs) and one user message holding the direction. The fixed instructions say where the model may
work, from the SDK's tool definitions (runner-tools: "Tool definitions tell the model where it may work").

Each SDK tool becomes a `ToolFunctionDef`: its name and description unchanged, and each `Field` a parameter of the
matching Python type (`str`, `int`, `bool`), `Annotated` with its description and, for an integer, its minimum. An
optional field gets a default of `msgspec.UNSET` (type `T | UnsetType`), which the implementation leaves out of the
input. The probe showed a default of `None` makes the library send `anyOf: [T, null]`, while `UNSET` sends exactly the
SDK's property and rejects `null`. The schema the library sends is then the SDK's input schema without
`additionalProperties: false`, which the library can't express. A test compares the two field by field (the spec's
"The model is offered the SDK's tools"), so a library change that alters what the model sees fails a test, not a run.

The implementation for each tool calls `Tools.run` with the arguments the library converted, a call id the runner
makes up (the library doesn't pass its own to the implementation), and the run's event numbering. It returns the
result's text, and the runner reports the `ToolStep`'s pair. `max_parallel_tool_calls` stays 1, so calls run in the
model's order.

**What the library changes about a malformed call.** The library converts arguments before troupe sees them, so:

- an unknown tool or a conversion failure goes to `handle_invalid_tool_request`, where the runner calls `Tools.run`
  with the request's raw arguments. That produces the SDK's own error and the paired events, so the model sees
  troupe's message, not the library's;
- an argument name the tool doesn't define is dropped by the library without error, so troupe never sees it, and the
  call goes ahead without it. The SDK would have refused it. This is the one place the runner can't keep the SDK's
  behaviour. It's pinned by a test so it can't change unnoticed, and filed upstream as a request to forbid unknown
  fields (D13).

### D8. Mapping rounds to events

- **Text**: the library streams each round's fragments to `on_prediction_fragment`, each with a `reasoningType`:
  `none` for the answer, or `reasoningStartTag`, `reasoning` and `reasoningEndTag` for thinking. Turns are built from
  the `none` fragments only. The probe found that a round's result content and its assistant message hold the thinking
  too (`<|channel>thought … <channel|>`), so a round's content is never used as its text. The library starts a round's
  tool calls as they stream, before the round's `on_prediction_completed`, as the probe confirmed. So the runner reports
  the text streamed so far as a `turn` when the round's first call starts, and any after it when the round ends, which
  keeps each turn before the calls that follow it.
- **Round end** (`on_prediction_completed`): the round's stats are added to the run's token counts, and the budget is
  checked (D5).
- **Tool calls**: each reported by its implementation (D7) as it runs.
- **The end**: `act()` returns after a round with no tool calls. A round whose `stopReason` is `eosFound` or
  `stopStringFound` ends `ok`. `contextLengthReached`, `maxPredictedTokensReached`, `modelUnloaded` and `failed` end
  `error`, saying which. The turn limit and the token budget end `error` (D5).
- **The library's exceptions** (`LMStudioClientError`, `LMStudioServerError`, `LMStudioPredictionError`,
  `LMStudioWebsocketError`, `LMStudioTimeoutError`, `LMStudioCancelledError`) map to `error` results, or to retries
  (D10), each naming what failed. A cancelled prediction after troupe's cancel sends nothing (D9).

### D9. Threads and stopping

The main thread reads troupe's messages and answers them. After `run/start` is acknowledged, a worker thread sends
`init`, loads the model and runs `act()`. The library runs its websocket on a thread of its own, and calls each tool's
implementation on a pool thread. Every line goes to standard output whole, under one lock, as in the other runners.

Stopping (on `run/cancel`, end of input, `shutdown`, the token budget, or a fatal error) sets a flag under that lock
first, so no event can follow the acknowledgement, and every implementation checks the flag before calling
`Tools.run`, so no call runs after it. Then the runner closes the client, which closes the websocket: `act()` doesn't
hand back its prediction stream, so closing the client is the cancel. The probe confirmed that closing it from another
thread mid-prediction makes `act()` raise `LMStudioWebsocketError` at once, LM Studio goes back to idle, and the
process exits within a second, with only the library's one daemon thread left. The runner exits within its own named
grace, below troupe's, whether or not the library's threads have finished. If they keep the process alive past the
grace, the runner ends it from its own exit path.

### D10. Retries, redirects and timeouts

- **Retries** are the runner's: a connection that fails, or drops, before any tool call has run is retried with a
  `retry` event, within a named number of attempts and backoff. After a call has run, the runner doesn't retry,
  because `act()` would start the chat again from the direction and could run a tool twice. The library makes none of
  its own, and a test pins that one dropped connection gives exactly one `retry` event.
- **Redirects** aren't followed. httpx doesn't follow them unless asked, and the library doesn't ask. The greeting
  check treats any 3xx as "not LM Studio here" (`lm-studio.unreachable`, naming the status and the location). A test
  pins that nothing connects to the location.
- **Timeouts**: every timeout the library applies comes from one of the runner's named settings, never the library's
  default (runner-protocol, "Retries follow troupe's named limits, not the library's", from #333): the wait for server
  messages for each handle, the websocket's close (`WS_DISCONNECT_TIMEOUT`), and the greeting check's HTTP timeout.
  Where the library offers no knob, the call runs under the runner's own named deadline. Load progress,
  prompt-processing progress and prediction fragments count as messages, so a long but live round isn't a timeout.
- **#333's guarantees** (runner-protocol's requirements for a runner with a library, listed in
  `contributing/runners.md`, "Runners with client libraries"): retries and timeouts as above; no redirect and the
  credential only in its header (here no credential is ever sent, D4, and the passkeys the library makes up are scrubbed
  from fixtures); cancel within the grace (D9); the transcript as the library exposes it (D11); and pinned dependencies
  on the licence list, certifi only from PyPI (D15, task 4.1). The runner's tests show each against the fake endpoint.

### D11. The transcript is what the library exposes

Following #319, the transcript holds the exchange as the library exposes it, serialised, before any event it leads to:
the model's downloaded info, the chat and the tools' JSON schemas as sent, each round's result (content, reasoning,
stats, model info), and each tool result message from `on_message`. The runner accepts #294's `transcript-kinds`:
what it passes the library (the chat, the tools, each tool result) is `sent`, and what the library gives back (the
model's info, each round's result, which holds the assistant message and its tool requests) is `received`. A host that
offers no kinds gets the same records without them, as the contract requires.

**What that loses compared with wire bytes:** the websocket frames themselves (the handshake, channel framing and
message ids), the prediction's fragments as they streamed (the round's result has the whole text), the prompt as
LM Studio rendered it through the model's template, and any message the library reads and drops. The fragments and
prompt-processing progress are available through callbacks. They aren't kept, because they repeat what the round's
result holds, and the transcript is limited by the run's limits.

The library logs through Python's `logging` (its `lmstudio` loggers). The runner keeps those loggers off standard
output and passes only warnings and above to standard error, cut to fit.

### D12. A probe first, and fixtures from it

The library's source left gaps this design leaned on, so the first task was a probe through `lmstudio` 1.5.0 against
the owner's LM Studio 0.4.28 (build 2), with `google/gemma-4-e4b`, run from the scratchpad and never committed
(2026-11-08; findings on troupe#291, issuecomment-6716206227). It settled the context length against a loaded model
(D5), the order of calls, text and round completion (D8), reasoning inside a round's content (D8), the turn limit's
last round (D5), optional parameters' schema (D7), the missing-argument path (D7), cancel by closing the client (D9),
and that nothing reports LM Studio's version (D6). It didn't probe "Require Authentication" (the runner refuses a
credential anyway, D4), and the model wouldn't call an unknown tool, so that path rests on the library's source and a
unit test.

Recorded runs go in the fixtures (with provenance: LM Studio's version, the library's version, the model and the date).
The capture tool (`tools/capture_lm_studio.py`) records a run's websocket exchange through a recording
proxy between the library and LM Studio, and scrubs the client passkeys and the host's paths.

### D13. The contract and library gaps, found so far

The gaps the OpenAI runner filed have all landed in the contract since this change was proposed, and the runner
keeps each (D16): an error result's `reason` (#296), an estimated cost from troupe's price (#292), what `inputTokens`
counts (#293), transcript record kinds (#294), and the model that served a run (#295).

New candidates. Each is filed as its own issue on the board once building confirms it (#239, #291), checking #56's,
#162's and #319's issues first so nothing is filed twice:

1. **`lmstudio` can't send an API token** (D4). Filed upstream on lmstudio-python, and as a troupe issue to adopt it.
2. **`lmstudio` drops unknown tool arguments without error** (D7). Filed upstream as a request for a strict option.
3. **Retry safety.** The contract's `retry` event has no notion that retrying after side effects isn't safe. This
   runner refuses to (spec), but nothing tells troupe why a run that could have been retried wasn't.
4. **A transcript that isn't wire bytes.** #319 allows it, and #333 settled it: a library-backed runner's `sent` and
   `received` records hold what the library exposes (runner-protocol). No longer a gap.

### D14. Testing

- **A fake LM Studio endpoint** (`tests/fake_lm_studio.py`): an HTTP and websocket server on loopback that answers the
  library's greeting and replays recorded websocket exchanges, matching each of the library's requests to the
  recording by its method and channel, and rewriting the ids and passkeys the library makes up. Its scripts can drop
  the connection, stall, redirect the greeting, or stream a prediction slowly. It records everything the library sent.
  The library's websocket protocol is LM Studio's, not a documented one, so the fake is only as good as its recordings.
  They're captured from a real LM Studio (D12), and each says which LM Studio and library versions it came from.
- **Fixtures** in `plugins/runner-lm-studio/fixtures/<name>/`: recorded from the probe, or built from recorded shapes
  where a case can't be had on demand (a dropped connection, a stall), and each says which.
- **Unit tests** at the library seam: the tool definitions' schema against the SDK's (D7), the round-to-event mapping
  fed with the library's own result objects, and the options parser against its published schema (a property test).
- **Conformance:** `check_runner`, given a runtime on the fake endpoint.
- **The live test**, `TROUPE_LIVE_LM_STUDIO=1`: the runtime from the person's environment, a model pinned in the test,
  and low limits.
- Every test runs on Linux, macOS and Windows, on every supported Python.

### D15. Shipping it

The runner joins everything the other runners are part of: the `uv` workspace, the typing and lint paths, the import
contracts (and an I/O seam contract naming its one module that imports `lmstudio`), `scripts/check.py`'s scopes
(`runner_lm_studio`) and `check-paths.toml`, release-please's config and manifest, and the changelog page.
`interim.RUNNERS` gains `lm-studio` (D3).

It ships as an optional extra of `troupe-run`, by #333's mechanism, not in the base install, so only people who want it
carry `lmstudio` and its dependencies. The extra is named exactly after the runner, `troupe-run[lm-studio]`, the rule
recorded on #333 for every runner's extra (owner, 2026-11-07: be consistent). An actor on the runner without it
installed gets #333's error naming the extra. If #333 hasn't landed when the runner is ready, this pull request waits
for it rather than adding `lmstudio` to the base install.

**Python versions.** troupe supports Python 3.12 to 3.15. `lmstudio` needs 3.10 or later, and msgspec, which it pulls
in, is a compiled package. msgspec 0.22.0 has wheels for cp312 to cp315 on Linux, macOS and Windows (checked
2026-11-07), and the rest of the tree is pure Python.

The audition names its model in one place (`LM_STUDIO_AUDITION_MODEL`): `google/gemma-4-e4b`, the 4B model the probe
ran, which LM Studio marks as trained for tool use and which called tools in every probe round, with `maxTurns` 10
and `maxTotalTokens` 100,000, as the OpenAI audition's. `init` prints the extra to install, that LM Studio's server
must be running with "Require Authentication" off, and the `lms get` for the model.

The spec `lm-studio-runner` is new, so its Purpose goes into troupe-run/infrastructure's
`oob/troupe-spec-purposes.json`, in a pull request that merges right after this one (troupe first, as for
infrastructure#263, so neither waits on the other). The `runtimes` spec changes a requirement, not its Purpose.

### D16. The contract as it now stands

Five contract changes landed on main while this one waited for #333, and the runner keeps each:

- **`reason`** (#296): every `error` result names one reason from the contract's closed list. `turn-limit` and
  `budget` (D5), `context-length` for `contextLengthReached`, `output-limit` for `maxPredictedTokensReached`, `engine`
  for `modelUnloaded` and `failed`, `network` for a lost connection, whether retries ran out or a call had already run
  (D10), `cancelled` after `run/cancel` (D9), and `other`, its message naming what happened, for anything else.
- **`estimatedCostUsd`** (#292): LM Studio reports no cost, so `costUsd` is always absent. When `run/start`'s runtime
  carries a price, the result estimates the run's input and output tokens at it. A price with a cache rate gets no
  estimate, since LM Studio reports no cache counters and the contract forbids pricing one kind of token at another's
  rate.
- **`inputTokens`** (#293): each round's `promptTokensCount` summed. LM Studio reports no cache reads or writes, so
  neither cache counter is sent.
- **Transcript kinds** (#294): `sent` and `received`, as D11 says.
- **`served_model`** (#295): each round's result names the model key that answered (`model_info.modelKey`). When it
  isn't the run's model, the runner reports it once, before that round's events. In the probe it was always the model
  asked for.

## Risks / Trade-offs

- **A library troupe doesn't control.** `lmstudio` can change what it sends, how it converts arguments, or its
  threading in any release. → It's pinned, the schema test (D7) and the fixtures catch a change in what the model sees
  or what comes back, and a bump is a change of its own, rerun against the live test.
- **The fake endpoint replays an undocumented protocol.** → Recordings come from a real LM Studio and carry their
  versions. The unit tests at the library seam don't depend on the protocol, and the live test is the check against a
  real LM Studio.
- **Unknown tool arguments are dropped, not refused** (D7). → Pinned by a test, and filed upstream. The call that runs
  is still checked against the effects, so the drop can't widen what an actor may touch.
- **No API token.** People who run LM Studio with authentication on can't use the runner. → A clear refusal, the
  README, and the upstream issue (D13).
- **Plain `ws://` to a remote LM Studio.** → No credential is ever sent (D4), and the README says the traffic isn't
  encrypted.
- **Stopping goes through the library's cancel or close** (D9). → The probe settles which, and the runner's own grace
  bounds the exit either way.
- **Dependencies for an optional runner.** → They're only in the extra (D15).
- **Breaking the built-in `lm-studio` runtime.** → troupe is pre-release, no audition or doc uses the old value, and
  `lm-studio.unsupported-endpoint` names the fix for anyone still on it.
