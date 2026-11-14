# Design: in-process-runner

## Context

See proposal.md, "Why". The evidence behind this design is the probe on #414 (comment 6866903650), plus three later
measurements made while designing:
- A KV budget (`memory_goal`) is refused on CPU (`an explicit memory goal requires supported paged attention`), so on
  Linux and Windows the engine doesn't cap the KV cache.
- With a capped KV budget on Metal, an over-budget prompt is refused at once, and an answer that grows past the budget
  raises `ValueError("Sequence 1 with 1025 tokens exceeds the total KV cache capacity of 1024 tokens.")`.
- Loading weights takes about 1 s per 0.6 GB here, and the first Metal kernel warm-up on a machine takes 11–20 s.

Constraints that shape the design:
- **troupe's start limit.** The host gives `initialize` and `run/start` together `RUNNER_START_TIMEOUT_SECONDS`
  (30 s). It is a code default, not a person's setting.
- **Runtimes need an endpoint.** Every runtime has an `http(s)` endpoint today. `run/start`'s `$defs/runtime` requires
  one, and `RuntimeFit` judges a runtime by its endpoint's shape.
- **No shared runner skeleton.** The plugin SDK has the tools, events, compaction and cost helpers but no shared
  JSON-RPC server, so each runner has its own `runner.py` and loop. The Ollama runner is the model for this one.
- **The library's API.** `mistralrs` 0.9.5 is MIT and has no Python dependencies. Its API is one class,
  `Runner(which=Which.GGUF(...), ...)`, with `send_chat_completion_request` (blocking, or streaming), `tokenize_text`,
  `max_sequence_length`, and no cancel. Its errors are plain `ValueError`s.

## Goals / Non-Goals

**Goals:**
- Show that troupe's guarantees (#319, #279, cancel within the grace) hold when the engine is a thread in the runner
  rather than a request it can close.
- Keep the conversation (tool loop, events, transcript, compaction) as close to the Ollama runner's as the engine
  allows, so the two read the same.

**Non-Goals:**
- Sharing a runner skeleton with the Ollama runner. That's worth doing once three runners have the same shape, as
  its own change.
- CUDA or other GPU builds (`mistralrs-cuda` and similar), multi-file GGUF, safetensors models and Hugging Face model
  ids.
- Throughput. One run is one process with one sequence.

## Decisions

### D1. One process per run: the protocol on the main thread, the engine on a worker

As in the Ollama runner (local-model-runner D3), the main thread reads troupe's messages and answers them, and a
worker thread loads the model and runs the conversation. Both write to standard output one whole line at a time,
under one lock. The engine's calls block the worker. The probe showed `mistralrs` releases the GIL while it works (a
50 ms ticker kept ticking, with a largest gap of 0.06 s on Linux and macOS and 0.45 s on Windows), so the main thread
keeps reading. The engine is loaded once per process, with `max_seqs=1`.

*Alternatives.* Loading on the main thread was rejected, because end of input during a load would go unread.
`asyncio` was rejected because it adds nothing: the engine's calls are blocking native calls either way.

### D2. Cancel, end of input and shutdown end the process

The engine can't be interrupted from Python, so stopping means leaving. On `run/cancel`, end of input or `shutdown`,
the main thread does four things:
1. It sets the stop flag under the output lock, so the worker writes nothing more.
2. It acknowledges, when there's a request to acknowledge.
3. It flushes.
4. It exits with `os._exit`, abandoning the engine's call in flight.

`os._exit` skips Python's finalisation, which would otherwise wait on nothing useful and run atexit handlers while a
native thread still holds the engine. Before exiting, it waits up to `STOP_GRACE_SECONDS` (2 s) for the worker to
reach a point where it isn't writing, as the Ollama runner does.

The probe measured troupe's shape (a parent and a child over pipes, generating on a worker): exit took 0.02–1.2 s on
macOS, 0.07–0.37 s on Linux and 0.12–0.6 s on Windows, mid-decode and mid-prefill. That's well below the 10 s grace.

*Alternatives.* Streaming, checking the stop flag between chunks and dropping the stream was rejected as the way to
stop. The probe showed that dropping the stream does abort the sequence, but a long prefill sends no chunk for
minutes, and the process ends anyway.

### D3. The protocol channel is kept before the engine is imported

`mistralrs` writes its log lines to file descriptor 1 when that's a pipe. The runner's entry point does four things
before any import of `mistralrs`:
1. It duplicates fd 1 (`os.dup`).
2. It opens the duplicate as the protocol writer.
3. It points fd 1 at fd 2 (`os.dup2(2, 1)`).
4. It rebinds `sys.stdout` to standard error.

From then on, anything the engine or a stray `print` writes reaches troupe as runner stderr, which the host keeps
within `stderrMaxBytes`. On Windows, the C runtime's `_dup2` on descriptors 0–2 also moves the Win32 standard handle
that Rust's standard output uses. The probe's pipe test showed this: on Windows, the child's first standard-output
line was the probe's own, though the engine had logged before it. The `mistralrs` import is confined to one module,
`engine.py`, which an import-order test and an import-linter contract keep from loading before the entry point has
moved fd 1.

*Alternatives.* Turning the engine's logging off was rejected. It has no Python switch, and its log lines are useful
on stderr.

### D4. What's checked before the acknowledgement, and the load after it (owner, 2026-11-14)

Loading the model can take longer than troupe's 30 s start limit, so the runner checks only what's quick before it
answers `run/start`:
- the scratch directory and the options;
- the runtime: present, no endpoint, no credential;
- the model: an absolute path, an existing file that starts with the GGUF signature (`GGUF`);
- the installed `mistralrs` version against `requirements.json`;
- on macOS only, that this Python can compile mistral.rs's Metal kernels.

That last check loads the packaged 1.2 MB model (`stories260K.gguf`, D10) with paged attention off. In the probe, that
model reproduced both Metal failures (SDK 12.1 and SDK 27) in under a second once warm. A Metal library compile
failure becomes `mistralrs.unsupported-python`, naming `sys.executable` and the version. Its fix is
`uv tool install --managed-python --no-sources "troupe-run[mistralrs] @ ..."`.

**How long the check takes.** The check model's load compiles mistral.rs's Metal kernels the first time on a
machine, and they're cached on disk after that. Measured:
- GitHub's macOS runners (fresh M1 VMs, nothing cached): 15.4–19.6 s across 10 legs.
- This Mac's first run: 16.4 s.
- Every later run: 0.2 s.

`initialize` and the other checks take well under a second, so a first run's acknowledgement fits troupe's 30 s
start limit, with at least 10 s to spare on every machine measured. A much slower or heavily loaded Mac's first run
could still pass 30 s, which troupe reports as `runner.start-timeout`.

**A compile cut off keeps what it did.** On fresh GitHub macOS runners, a load of the check model was killed after
3, 8 and 12 s, then loaded twice more:

| Cut off after | Next load | The one after |
|---|---|---|
| 3 s | 16.4 s | 0.70 s |
| 8 s | 7.6 s | 0.63 s |
| 12 s | 2.9 s | 0.60 s |
| not cut off (about 20 s) | 0.65 s | 0.60 s |

Every next load succeeded. The cache is macOS's own, per user, keyed by the GPU compiler's version, and it keeps
each compiled library as it's written, so a cut-off compile is never left broken. The next load picks up where the
last stopped, and retrying finishes it.

**The cache is warmed before the first run** (owner, 2026-11-14). A runner's entry in `RUNNERS` can name `warm_up`
arguments. `troupe init --audition` runs the runner once with them, after it records the audition, within
`RUNNER_WARM_UP_TIMEOUT_SECONDS` (120), and with the environment a run would have. For mistralrs that's
`python -m troupe_runner_mistralrs --warm-up`, which loads the check model on macOS and does nothing elsewhere, and
writes one JSON line. How it went is a notice:
- `runner.warmed-up`, with how long it took;
- `runner.warm-up-failed`, with the runner's own problem and fix (an unsupported Python is caught here, at setup);
- `runner.warm-up-cut-off`, saying the first run finishes it.

The run-time check stays as the backstop, for an actor set up without an audition, and for a warm-up that was cut
off.

*Alternatives the owner named:*
- **Warming when the extra is installed** was rejected: a wheel has no install hook.
- **Warming when the runtime or an actor is configured** was rejected: it would put a 20 s side effect on a
  `troupe config set`.
- **A `troupe` command** was deferred: a new command surface for one runner's cache. Adding it later is additive,
  since the warm-up is already a function in core.

After acknowledging, the worker sends a `log` that it is loading the model and loads it within `LOAD_TIMEOUT_SECONDS`
(600). A load that fails ends the run with `error`, reason `configuration`, holding the engine's message. So does a
load that passes the limit, after which the process exits, since the load can't be stopped. This matches the Ollama
runner, where Ollama failing to load a model is an error result after the acknowledgement.

*Alternatives, put to the owner, who chose 2 on 2026-11-14:*
1. Load before the acknowledgement, letting a runner's `initialize` answer ask for a longer start, up to a ceiling
   in core. This would be a runner-protocol and host change.
2. **(Chosen.)** The quick checks above, including the packaged-model check on macOS, before the
   acknowledgement.
3. As 2, without the packaged model. The unsupported-Python failure would then be an error result after the
   acknowledgement, not a refusal.

Pre-checking the interpreter's build SDK (`LC_BUILD_VERSION`) was rejected. The window of working SDKs (15–26.5
observed) is a heuristic that would refuse working setups and miss other causes.

### D5. An in-process runtime: the built-in `mistralrs`, with no endpoint

The model is a file on the machine that runs the runner, so it belongs to the person, like an endpoint. It comes from
`TROUPE_RUNTIME_MISTRALRS_MODEL` or an actor's `model` through the existing resolution, not from runner options.

troupe gains one built-in runtime, `mistralrs`, with no endpoint. The changes:
- `endpoint` becomes optional in `protocol/schemas/runtime.schema.json`'s resolved runtime, in the config schema and
  in `run-start.schema.json`'s `$defs/runtime`.
- Core keeps the rule that a runtime of your own needs an endpoint, so only the built-in is in-process.
- `RuntimeFit` gains `endpoint: Literal["required", "none", "any"]`. Ollama, OpenAI and LM Studio are `required`,
  `mistralrs` is `none`, and the scripted runner is `any`. Fit names the missing or unwanted endpoint, and the
  `runtime.unfit` refusal reads it the same way.
- Config refuses `runtimes.mistralrs.endpoint`, and resolution refuses `TROUPE_RUNTIME_MISTRALRS_ENDPOINT` as
  `runtime.invalid-value`.

Which built-ins are in-process is a property of the built-in in `defaults.py`, in one place.

*Alternatives.*
- The model in runner options was rejected. It breaks "the model comes from the runtime" and the per-person override,
  and puts a host path in shared config.
- A pseudo-endpoint such as `inproc://` was rejected. It claims a shape that isn't there, and every endpoint check
  would need an exception.
- Runtimes of your own without an endpoint were rejected for now. One built-in, with the actor's `model` for a second
  model, covers what's needed. Allowing them later is additive.

### D6. How the runner uses `mistralrs`

The model is loaded with:
- `Runner(which=Which.GGUF(quantized_model_id=<dir>, quantized_filename=<name>), token_source="none", max_seqs=1,
  seed=<seed>)`. `token_source="none"` means Hugging Face is never asked for a token.
- On macOS, `memory_goal=f"{window}tokens"` (D7). Paged attention stays at the engine's default elsewhere.

Each request is one blocking `send_chat_completion_request(ChatCompletionRequest(...))`:
- `messages` are the conversation.
- `tool_schemas` are the SDK's definitions as OpenAI-style function JSON, and `tool_choice` is `Auto`.
- `max_tokens` is the room left (D7).
- `temperature` comes from the options when set, and `enable_thinking` from `think`.
- `truncate_sequence` is `False`, and `max_tool_rounds` and `tool_dispatch_url` are unset.
- No `tool_callbacks`, MCP, search, shell or code execution is configured on the `Runner`, so the engine never runs a
  tool itself. The tools are troupe's, so the engine's are off.

Streaming isn't used. One response object carries `finish_reason`, `usage` and the tool calls, and stopping doesn't
need it (D2). The response's `model` is the id the runner gave, so there's never a `served_model` event.

### D7. The context window: set always, enforced by the runner on every OS

- **Window.** It is `contextLength`, else `DEFAULT_CONTEXT_LENGTH` (16384, as the Ollama runner), lowered to
  `max_sequence_length()`. A `contextLength` above the model's length ends the run with `configuration` after the
  load, since the length is known only then.
- **KV budget.** On Metal, the window is also the KV budget (`memory_goal`). That sizes the cache for a small Mac
  (fix 3 of the probe) and makes the engine refuse past the window. CPU builds refuse a KV budget, so they get none.
  On CPU the runner's own bound below is what holds.
- **Counting.** Before each request the runner counts the conversation: `tokenize_text` of each message (counted
  once, when it's added or stubbed), plus `MESSAGE_OVERHEAD_TOKENS` per message for the chat template, plus the
  tokenized tool definitions and `TOOLS_OVERHEAD_TOKENS` for the template's preamble. From the second request on, it
  adds the difference between the engine's prompt count and the runner's at the last request. In the first live run, the real prompt was 1,432
  tokens, mostly the SDK's tool definitions, so `contextLength` is at least 2048 and `TOKEN_MARGIN` is 256.
- **Bounding the answer.** `max_tokens` is the window less that count, less `TOKEN_MARGIN`. With no room left, a run
  told `fail` ends with `context-length` before sending.
- **What counts as a full window.** A `finish_reason` of `length` can only mean the answer reached the window, since
  the runner sets no other output cap. It ends the run with `context-length`, and its tool calls aren't carried out,
  since they may be cut. So do the engine's two length refusals ("Prompt sequence length is greater than",
  "exceeds the total KV cache capacity"). These are matched in one table in `port.py`, with a test of each
  message, so a wording change in a new `mistralrs` fails a test rather than becoming `engine`.

The runner never sends `output-limit`. #279 kept `output-limit` for an answer cut at an engine's own output cap, and
this runner has none. Saying `output-limit` for an answer that filled the window would hide that the window, which
the person can set, was the limit.

### D8. Compaction when told `compact`

This is the Ollama runner's algorithm, on exact counts:
- Before a request whose count is over the SDK's `COMPACT_AT_SHARE` of the window, the runner replaces old tool results with
  the SDK's stub (`compaction.choose`/`stub`), oldest first, until the count is at or below the SDK's `COMPACT_TO_SHARE`. It
  sends a `context` event (`truncated`, `by: runner`) first.
- After an engine length refusal, or a `length` stop, it compacts and asks again, without counting a turn. A
  `length` stop's partial answer is kept in the transcript, not in the conversation.
- With nothing left to remove, the run ends with `context-length`.

### D9. #319's guarantees, in process

| #319 guarantee | Here |
|---|---|
| Retries follow troupe's limits, library retries off | There is nothing to retry. Every failure is local and deterministic (a load error, a length refusal, an engine error), so none is retried and no `retry` event is sent. The library has no retry setting. |
| Every library timeout from a named setting | The engine has no timeouts. The runner bounds the load with `LOAD_TIMEOUT_SECONDS`. A request is bounded by its `max_tokens` and by troupe's run timeout. A request can't be cut short from inside the process; cancel ends the process (D2). |
| No redirects; the credential only in its header | There is no network and no credential. A runtime with either is refused before the acknowledgement. `token_source="none"` keeps any Hugging Face token unread. |
| Cancel and end of input stop the request within the grace | D2. |
| Every limit a named setting | Every setting is in `defaults.py` and documented in the README, with a test that each has a row. |
| Pinned, licence on the list, installs everywhere | `mistralrs==0.9.5` (MIT, no Python dependencies) is pinned in the plugin and the lock. The install check installs `[all]` on every leg. The wheel bundles compiled Rust crates (candle and others) whose licences the lock-based check can't see. They are recorded here as a known gap, and the upstream project's licence review covers them. |

**What the transcript leaves out compared with a wire.** There's no wire. The `sent` records are each
`ChatCompletionRequest` as the runner built it, serialised from the fields it set (with `tool_schemas` as parsed JSON).
The `received` records are each `ChatCompletionResponse` as returned, serialised from its attributes. Before each
later request, the transcript holds the messages added since and that request's settings, since its `max_tokens`
(the room left) changes every turn. Left out:
- the prompt the chat template rendered, and the token ids;
- the engine's own log lines, which go to stderr (D3);
- the timing fields in `usage` beyond the token counts.

The token counts stay, in the record.

### D10. Tests without a downloaded model

**The packaged model.** `stories260K.gguf` (1.2 MB) ships in the package under
`troupe_runner_mistralrs/check_model/`. Its weights are `stories260K` from karpathy/tinyllamas (MIT, the llama2.c
project), and the GGUF conversion is ggml-org/models' `tinyllamas/stories260K.gguf` (SHA-256
`270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d`). Beside it is a `PROVENANCE.md` holding both
sources, the MIT licence text, the SHA-256 and the date fetched, which the owner asked for on 2026-11-14. It serves the macOS check
(D4), and it lets tests run the real engine on every OS:
- loading it;
- the protocol channel (D3), by a test that runs the runner process with it and checks every stdout line parses as
  a contract message;
- cancel and end of input while it loads and answers (D2);
- the KV refusal's wording on Metal.

It has no chat template or tool calling, so it can't play a conversation, and it answers in milliseconds, so no test
can catch it mid-answer. Cancel mid-request is tested with the stand-in holding a request open, as the engine does
(the GIL released, nothing to interrupt), and with a real model mid-answer by the live test.

**The engine stand-in.** The runner reaches the engine through a small `Engine` protocol in `engine.py` with three
methods: load, chat and count tokens. Tests give the runner a stand-in that serves recorded responses. Production code
has no hook. Tests start the runner through a test-only entry script that passes the stand-in to `runner.main`, and
the conformance suite takes that script as its command.

**Fixtures.** `tools/capture_mistralrs.py` runs a real model (Qwen3-0.6B, Qwen's own Q8_0 GGUF) through the real
engine and writes, per case:
- `provenance.json`: the `mistralrs` version, the model and its SHA-256, the date;
- `run.json`;
- `responses.json`: the serialised responses;
- `engine.json`: the model's length and every token count, so a replay counts and bounds exactly as the run did;
- `expected.json`: the events and the transcript kinds.

The cases:
- `tool-call`: a read and an answer;
- `two-calls`: two calls in one answer;
- `effects-refused`: a refused `Delete`, which the model repeats until the turn limit;
- `length-stop`: an answer that fills a 2048-token window.

There is no compaction fixture. Qwen3-0.6B reads every file it's asked for in one reply, so there's never an older
turn's result to stub, and a fixture named for compaction that doesn't compact would claim more than it shows.
Compaction is tested with the stand-in. The engine's length refusals have no fixture of their own: the runner's
bound keeps a real run from reaching them. Each refusal's recorded wording is tested against the table.

**Live test.** One test runs only when `TROUPE_LIVE_MISTRALRS` names a GGUF file.

**Audition.** The install check rehearses an audition on every runner. A rehearsal doesn't load a model, and the
audition names no model; the person sets `TROUPE_RUNTIME_MISTRALRS_MODEL`. The init note says where to get a GGUF
file and how to point troupe at it.

### D11. Wiring and docs

The plugin follows the LM Studio extra's list (runner-extras D5):
- `RUNNERS` entry: `in_extra`, `runtime: required`, a fit with no endpoint and no credential, and the built-in
  `mistralrs`;
- an audition and an init note;
- workspace, mypy, ruff, pytest and import-linter entries;
- a `check-paths.toml` scope;
- a release-please package.

The install page gains the extra's row. On macOS it uses `--managed-python`, saying why, as the owner decided.
`docs/stagecraft/runtimes.md` gains the built-in and a "no endpoint" column in the fit matrix.

## Risks / Trade-offs

- **A large model may not fit in the runner's memory.** The model lives in the runner process, so running out of
  memory kills the runner, and troupe sees a runner that exited without a result.
  → The docs say so. The default window is modest. On Metal the KV budget bounds the cache.
- **The Metal compile depends on the interpreter's build SDK.** Upstream can move the working range either way.
  → The packaged-model check refuses clearly. CI's macOS legs use uv-managed Pythons, the only ones known to work.
- **`mistralrs` is 0.x, and its error wording isn't an API.** The length refusals and the Metal error are matched by
  message. → An exact pin, a fixture per message, and a version check against published data. A bump is its own
  change, which re-captures fixtures.
- **On CPU, the engine doesn't cap the KV cache.** → The runner's own count and `max_tokens` bound hold the window.
  `TOKEN_MARGIN` absorbs counting error, and the engine's own model-length refusal backs it up.
- **Slow on CPU and at long contexts.** The probe measured 7–14 tokens/s for 0.6B on CI's Linux and Windows CPUs,
  and about 4.5 s per token at 40k tokens on Metal. → It's the engine, not a fault. troupe's run timeout still applies.
- **Platforms without a wheel**: macOS x86_64, Windows arm64, musl Linux. → The extra doesn't install there. The
  install page lists the platforms.
- **A 1.2 MB binary in the repository and the wheel.** → It is MIT, pinned by SHA-256, with provenance. It's the
  smallest model that exercises the engine.

## Migration Plan

This is additive. Removing the runner later means removing the plugin, its extra, its `RUNNERS` entry and the
built-in runtime. Configs naming them would then be refused as an unknown runner or runtime.

## Open Questions

None that change the specs or tasks.
