# Proposal: the OpenAI runner

Issue: [troupe#162](https://github.com/troupe-run/troupe/issues/162). Built on
[troupe#278](https://github.com/troupe-run/troupe/issues/278) (runtimes), and on
[troupe#290](https://github.com/troupe-run/troupe/issues/290), which decided the API it speaks.

## Why

The runner port (`contributing/runners.md`, `protocol/schemas/runner/`, contract version 0) has had one real engine
behind it, Claude Code, and now the Ollama runner (#277). A runner that drives a hosted API with troupe's own tool loop
completes 0.2.0's test of whether the contract is shaped around Claude Code (#139's amendment), while the contract is
still a draft and cheap to change. It brings what neither Claude Code nor a local model does: an API credential troupe
has to give a runner, and a hosted service's costs, errors and rate limits.

**It speaks OpenAI's Responses API** (#290, owner, 2026-11-05). The change was first written, and partly built, for
Chat Completions. Then a probe with the owner's key showed that over Chat Completions only OpenAI's two smaller models
call tools, and only with reasoning turned off, while over Responses every current model does. Local Ollama serves
Responses too. So the runner stays focused on one API, OpenAI's, rather than covering every compatible host; the Chat
Completions work is prior art for other runners (noted on #56).

## What Changes

- **A new runner plugin, `openai`** (`plugins/runner-openai`), that speaks the Responses API to OpenAI, or any service
  that serves it (local Ollama does), and runs the model's tool calls itself through the plugin SDK's file tools
  (#239, #240). It applies the actor's declared effects by checking each call (`init` says `checked`), and imports
  nothing of troupe's but the SDK.
- **The service is never asked to keep the conversation.** Every request is `store: false` and carries the whole
  conversation: after tool calls, the previous output items unchanged, reasoning included, then one
  `function_call_output` per call.
- **It takes its service from the run's runtime** (#278): the endpoint, the model and the credential come from the
  runtime troupe resolves, never from the runner's options or a value hard-coded in the runner. The credential is
  only ever sent in the request's `Authorization` header: never over plain HTTP to a non-loopback host, never after
  a redirect, and never into events, the transcript, logs or errors.
- **Every run is capped.** The runner's options are closed: a turn limit and a token budget, each with a default
  named in one place in the runner. With no price from the service, the token budget is what bounds a run's spend.
  Tests always run on low limits.
- **A hosted service's failures map onto the contract as it stands:** rate limits (with `Retry-After`), server
  errors, failed responses whose cause is the service's, network errors, timeouts and broken streams are retried and
  reported as `retry` events. A refused credential, quota, a context-length error, a refusal, an incomplete response
  and an exhausted budget end in an `error` result that says which.
- **Usage and cost:** each response's usage is summed into the result's four token counters, cache reads and writes
  apart. `costUsd` is set only when the service reports a cost; OpenAI reports none, so the result has no cost, as
  version 0 defines.
- **An audition:** `troupe init --audition --runner openai` defines an actor on the `openai` runtime, with a small
  current OpenAI model and a small budget.
- **Tests:** deterministic tests against a fake endpoint, fixtures that pair recorded service output with the events
  it maps to (recorded from OpenAI and from local Ollama), the runner conformance suite, and an opt-in live test
  against a real service, budget-capped and never run in CI.
- **troupe ships it:** `perform` knows the runner by name, passes it only the variables it needs, and the
  `troupe-run` bundle includes it.
- **The port's gaps it finds are filed, not worked around** (owner, 2026-11-04). This change builds on contract
  version 0 as it stands and uses its fields as they're defined. Each gap is filed as its own issue, and this runner
  adopts it when it lands. The candidates so far are in the design (D12).

Out: Chat Completions (#290), each engine's native API (#56), other providers' own APIs, troupe storing secrets itself
(parked on #278), and the runtime's config, resolution and endpoint rules, which are #278's.

## Capabilities

### New Capabilities

- `openai-runner`: the OpenAI runner: how it talks to a Responses API service, its tool loop, its options and limits,
  how the service's output and failures map onto run events, how the credential is handled, and how it's tested.

### Modified Capabilities

- `runs`: `perform` knows `openai` by name, says it requires a runtime, and passes it only the variables it needs.
- `config`: the OpenAI audition.
- `cli`: `troupe init --audition --runner openai`.
- `quality-check`: the OpenAI runner's package has its own check scope, `runner_openai`.

## Impact

- **New:** `plugins/runner-openai` (its package, published schemas, README and tests).
- **Core:** `troupe.core.interim` gains the runner's table entry, `troupe.core.audition` its audition, the CLI's init
  its note, and the conformance suite can give a runner a runtime.
- **Workspace and releases:** the root `pyproject.toml` (workspace member, typing and lint paths, import contracts),
  `release-please-config.json` and its manifest, `packages/troupe-run` (the bundle includes it), and
  `scripts/check-paths.toml`.
- **Docs:** `plugins/README.md`, `contributing/runners.md` (a "Mapping an engine: the Responses API" section), the
  changelog page and the user docs on choosing a runner.
- **Dependencies:** none new. HTTP is the standard library's, behind one module.
- **troupe-run/infrastructure:** `oob/troupe-spec-purposes.json` records the new spec's Purpose, in a pull request
  that merges after this one.
