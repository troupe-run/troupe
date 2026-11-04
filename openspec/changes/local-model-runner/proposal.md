# Proposal

## Why

The runner port (contract version 0) has one real engine behind it, Claude Code, so nothing yet shows whether the
contract is shaped around Claude Code. #277 (split from #56 on 2026-11-04) adds a second: a model served by Ollama on
the person's machine, driven through Ollama's own `/api/chat` API, with **troupe's own tool loop**. Here the runner,
not the engine, holds the conversation and runs the tools. That is the opposite of Claude Code, and the harder test
#56 was for. It's due now, while the contract is still a draft and before gates, escalations and flows build on it
(#139's amendment). It also gives troupe a runner that needs no credential, costs nothing per run and works offline.

LM Studio stays on #56. Its native API (`/api/v1/chat`) takes no client-defined tools, only MCP servers whose tool
loop LM Studio runs itself. So #56 covers it through its OpenAI-style API, blocked by #162. Serving troupe's tools to
an engine over MCP is parked for a milestone of its own (owner, 2026-11-04).

## What Changes

- **A new plugin, `plugins/runner-ollama/`** (package `troupe-runner-ollama`, runner name `ollama`). It speaks the
  runner contract through the plugin SDK, imports nothing else of troupe's, and uses only the standard library (no
  HTTP client dependency). It:
  - checks before acknowledging `run/start` that Ollama answers, that the model is there and that it can call tools,
    and refuses the run, naming the fix, when one doesn't;
  - sends the character as the system message and the direction as the user message;
  - streams `/api/chat` with the SDK's seven tool definitions, and carries out each tool call with the SDK's `Tools`.
    Each call is checked against the actor's declared effects (`init.effects: checked`), and its output goes back to
    the model as a `tool` message;
  - loops until the model answers without a tool call, or until `maxTurns` is reached, which is an `error` result;
  - always sets the model's context window (`contextLength`, or a named default lowered to the model's maximum),
    and never carries on past it. Ollama doesn't refuse a conversation that outgrows its window: it drops the start,
    the actor's direction among it. So when an answer reports that its prompt reached the window, the runner carries
    out none of that answer's tool calls, and ends the run with an `error` result naming the window. What a run
    should do instead, for every runner, is Decision #279. This is the conservative default until then, and it loses
    nothing;
  - maps the exchange onto run events: `init` (engine `ollama`, its version and the model), a `turn` for each answer
    with text, a `tool_call` and `tool_result` pair for each call, a `retry` for each retry of its own, and one
    `result` with the summed token counts. It reports no cost, since nothing tells it one;
  - stops at once on `run/cancel`, end of input or `shutdown`, closing the request in flight. It starts no process.
- **Options, closed and published as `options.schema.json`:** `model` (required), `endpoint`, `maxTurns`,
  `contextLength`, `temperature`, `seed` and `think`. The endpoint's default (`http://127.0.0.1:11434`) and every
  other limit are named settings in one place in the runner. Any http(s) endpoint is accepted, apart from one with
  credentials, a path, a query or a fragment in it. Restricting where a run may send the workspace's contents is
  policy's job, later (owner, 2026-11-04).
- **Errors of its own, published as `errors.schema.json`:** an unknown option, a malformed option, Ollama not
  answering, a model that isn't pulled, and a model that can't call tools.
- **Two gaps in the runner contract, fixed in the contract** rather than worked around in the runner (#56's scope):
  - **The transcript assumed the engine holds the conversation.** "The engine's native output" leaves out what a
    runner with its own tool loop sends the engine, the full tool outputs among them, though the contract says they
    belong in the transcript. The contract now says the transcript also holds what such a runner adds to the
    conversation, each message verbatim as it sent it. Re-sent history isn't recorded again, so the transcript grows
    with the run, not with the square of it.
  - **Retries assumed the engine retries.** A runner that is its engine's client retries for itself. The contract
    now says those retries are `retry` events too, with the same reasons.
- **`perform` knows the runner by name:** an `ollama` entry in the interim runner table, given no environment
  variables, as the scripted runner is.
- **`troupe init --audition --runner ollama`** defines an example actor on a small tool-capable model, which can edit
  files and has no file it must change, like the Claude Code audition.
- **Tests:**
  - a fake Ollama endpoint (a loopback HTTP server in the tests) serves streamed `/api/chat` answers;
  - fixtures captured from a real Ollama pin the fake's shapes, and their capture tool records them with no
    credential;
  - the runner passes the conformance suite against the fake;
  - an opt-in live test runs a real model only when `TROUPE_LIVE_OLLAMA=1` is set, and is never run in CI.
- **Docs:** the plugin's README, the plugins table, contributing/runners.md (the runner list, "Mapping an engine:
  Ollama", and the two contract amendments) and the user docs' runner sections.

## Capabilities

### New Capabilities

- `ollama-runner`: the Ollama runner: its preflight checks, its options and errors, its tool loop over `/api/chat`,
  how it maps the exchange onto run events and the transcript, cancelling, its fixtures and its opt-in live test.

### Modified Capabilities

- `runner-protocol`: the transcript holds what a runner adds to a conversation it holds, and a runner's own retries
  are `retry` events.
- `runs`: perform's runner table names `ollama`, which is given no environment variables.
- `cli`: `troupe init --audition --runner` names `ollama` among the runners troupe has.
- `config`: the Ollama audition's example actor.
- `quality-check`: a `runner_ollama` scope for the new plugin, and the SDK's scope reaches every runner's suite, not
  "both runners'".

## Impact

- **New:** `plugins/runner-ollama/` (code, schemas, tests, fixtures, capture tool, README, LICENSE, CHANGELOG).
- **Workspace wiring:** the root `pyproject.toml` (sources, dev group, ruff, mypy, pytest, import-linter contracts),
  `release-please-config.json` and `.release-please-manifest.json`, `scripts/check-paths.toml`, and `troupe-run`'s
  dependencies (the bundle).
- **Core:** `troupe.core.interim` (runner table), `troupe.core.audition` (the Ollama audition), and core's tests for
  perform, conformance and the host.
- **Contract:** `protocol/schemas/runner/run-transcript.schema.json`'s description, and contributing/runners.md. The
  wire shapes don't change, so the scripted and Claude Code runners need no code change.
- **Infrastructure:** the new `ollama-runner` spec's Purpose goes into troupe-run/infrastructure's
  `oob/troupe-spec-purposes.json` in a pull request merged after this one. No new capability label is needed.
- **Issues:** closes #277. #56 stays open for LM Studio, blocked by #162.
