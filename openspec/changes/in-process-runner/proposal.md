# Proposal: in-process-runner

## Why

Decision #412 (owner, 2026-11-13) replaced the LM Studio runner with two runtimes of a different structure. This is the
first one: a model loaded **inside the runner's own process**, with no server and no HTTP, through mistral.rs's Python
package `mistralrs` (#414). Every runner troupe has today talks to something outside itself: a CLI child process
(Claude Code), a hosted HTTP API (OpenAI) or a local server (Ollama). An in-process engine proves the runner port where
cancellation, timeouts and memory work differently: the work is a thread in the runner, not a request troupe can
close. Decision #319 says what a library-backed runner must still guarantee, and #279 says a full context ends the run
with `context-length`.

The probe (#414, comment 6866903650) showed it can hold on Linux, macOS and native Windows for Python 3.12–3.15. Tool
calls work through troupe's own loop. The engine releases the GIL. The runner process exits within 1.2 s of a cancel or
end of input, mid-answer or mid-prompt, against a 10 s grace. A full context is an error or a `length` stop, never a
silent cut. It also found three limits, each decided by the owner (2026-11-14):
1. mistral.rs's Metal kernels compile only under a macOS Python built against a supported SDK. They fail under
   python.org's 3.12 and under Homebrew's Pythons on macOS 27, and work under every uv-managed Python.
2. The engine writes its log lines to standard output, which is troupe's protocol channel.
3. A small Mac runs out of GPU memory unless the KV cache is sized.

## What Changes

- **A new runner, `mistralrs`**, in `plugins/runner-mistralrs`, installed as `troupe-run[mistralrs]` (the extra is
  derived from its `mistralrs` dependency, spec: installation). It loads a GGUF model file with `mistralrs` in its
  own process, drives it with troupe's own tool loop and the SDK's seven tools, checks each call against the actor's
  effects (`effects: checked`), and reports the run through the runner contract. It sends no credential, makes no
  network request and costs nothing per run. The model never comes from Hugging Face: the runner loads only a local
  file, with Hugging Face access off.
- **An in-process runtime.** troupe gains a built-in runtime `mistralrs` with **no endpoint**: its model is the path
  of a GGUF file, set per person with `TROUPE_RUNTIME_MISTRALRS_MODEL` or per actor with `model`. A runtime without an
  endpoint fits only a runner that runs its engine in process, and such a runner fits only a runtime without one.
  `run/start`'s `runtime` carries no `endpoint` for it.
- **Before it acknowledges a run, the runner checks what it can check quickly**: the options, the runtime, that the
  model is an absolute path to a readable GGUF file, and, on macOS, that this Python can compile mistral.rs's Metal
  kernels. It does the last by loading a 1.2 MB model bundled with the plugin. An unsupported macOS Python is refused
  with `mistralrs.unsupported-python`, whose fix says to install troupe on a uv-managed Python
  (`uv tool install --managed-python ...`). The install guide says the same.
  The real model loads after the acknowledgement, and a failure to load it ends the run with reason
  `configuration` (owner, 2026-11-14; design D4).
- **The cache is warmed before the first run** (owner, 2026-11-14). `troupe init --audition` runs a runner's
  warm-up once. For mistralrs, that loads the check model on macOS, so a first run doesn't wait for the Metal compile.
  The run-time check stays as the backstop. A compile cut off keeps what it did (measured), so a retry finishes it.
- **The engine never writes to the protocol channel.** Before importing `mistralrs`, the runner keeps standard output
  for itself and points file descriptor 1 at standard error, so the engine's log lines reach troupe as runner stderr.
  A test runs the real engine and checks that standard output holds only protocol messages.
- **The runner always sets the context window**, as `contextLength` or a named default, lowered to the model's own
  length. It enforces the window itself on every OS. It counts each request's tokens, refuses (or, told `compact`,
  compacts) a conversation that wouldn't fit, and bounds each answer to the room left. On Metal it also passes the
  window as the engine's KV budget, so a small Mac doesn't run out of GPU memory. A conversation or answer that
  reaches the window ends the run with `context-length`.
- **Cancel, end of input and shutdown end the process.** The engine's work can't be interrupted from Python, so the
  runner acknowledges, sends nothing more and exits, abandoning the call in flight (spec: runner-protocol, "A runner
  that uses a library stops its request on cancel and end of input"). Loading runs on a worker thread, so end of
  input during a load also exits at once.
- **Tests never download a model.** The engine's own behaviour (loading, standard output, cancel and end of input,
  the KV refusal) is tested with the bundled 1.2 MB model, which loads on every OS. The conversation is tested
  against recorded fixtures: real `mistralrs` responses captured from Qwen3-0.6B, replayed through a stand-in for the
  engine. A live test runs a real model only when `TROUPE_LIVE_MISTRALRS` names one.

Not in this change: GPU builds other than the wheel's own (CUDA packages); models other than a single local GGUF
file; downloading models.

## Capabilities

### New Capabilities

- `mistralrs-runner`: the in-process runner: identity, options, the pre-run checks and the macOS refusal, the
  protocol channel kept clean, the tool loop, the context window and its enforcement, compaction when told
  `compact`, cancel and end of input, transcript, fixtures and the live test.

### Modified Capabilities

- `runtimes`: a built-in in-process runtime, `mistralrs`, with no endpoint. A runtime's endpoint becomes optional for
  it, and runtime fit adds whether a runner needs an endpoint or takes none.
- `runner-protocol`: `run/start`'s `runtime` carries `endpoint` only when the runtime has one.
- `cli`: `troupe init --audition` warms its runner's engine, when the runner has a warm-up.
- `config`: a mistralrs audition, whose actor names the `mistralrs` runtime and no model, and whose init note says
  where the model comes from.

## Impact

- New plugin `plugins/runner-mistralrs` (MIT `mistralrs` 0.9.5 pinned; abi3 wheels for macOS arm64, Linux x86_64 and
  aarch64, Windows x86_64), with its own scope in `scripts/check-paths.toml`, release-please entry and workspace
  wiring.
- Core:
  - `RUNNERS` gains `mistralrs` (`in_extra`, a fit that takes no endpoint), and there's an audition and an init note.
  - The built-in runtimes gain `mistralrs`.
  - Runtime resolution and fit allow an endpointless built-in.
  - The schemas change: `protocol/schemas/runtime.schema.json`, `config/runtime.schema.json` and run-start's
    `$defs/runtime`, where `endpoint` becomes optional.
  - The conformance suite gains a test for the new runner.
- `troupe-run`'s optional dependencies gain `mistralrs`, and `all` gains it too.
- Docs:
  - `docs/opening-night/install.md`: the extra, and the uv-managed Python on macOS.
  - `docs/stagecraft/runtimes.md`: the built-in and the fit matrix.
  - `contributing/runners.md`, `plugins/README.md` and the changelog.
- troupe-run/infrastructure: the new spec's Purpose goes in `oob/troupe-spec-purposes.json`, in an infrastructure pull
  request merged right after this one.
- Overlap: #415 (Anthropic runner) may also add a built-in runtime. Whichever of the two merges second rebases its
  `runtimes` delta onto the other.
