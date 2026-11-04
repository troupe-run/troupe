# Proposal: the OpenAI-style runner

Issue: [troupe#162](https://github.com/troupe-run/troupe/issues/162). Depends on
[troupe#278](https://github.com/troupe-run/troupe/issues/278) (runtimes), which blocks it.

## Why

The runner port (`contributing/runners.md`, `protocol/schemas/runner/`, contract version 0) has one real engine behind
it, Claude Code. A runner that drives a hosted API with troupe's own tool loop is the second half of 0.2.0's test of
whether the contract is shaped around Claude Code (#139's amendment), while the contract is still a draft and cheap to
change. It brings what neither Claude Code nor a local model does: an API credential troupe has to give a runner, and
a hosted service's costs, errors and rate limits.

## What Changes

- **A new runner plugin, `openai-chat`** (`plugins/runner-openai-chat`), that speaks the OpenAI-style Chat Completions
  API to OpenAI or any compatible host, cloud or local, and runs the model's tool calls itself through the plugin
  SDK's file tools (#239, #240). It applies the actor's declared effects by checking each call (`init` says
  `checked`), and imports nothing of troupe's but the SDK.
- **It takes its service from the run's runtime** (#278): the endpoint, the model and the credential come from the
  runtime troupe resolves, never from the runner's options or a value hard-coded in the runner. The credential is
  only ever sent in the request's `Authorization` header: never over plain HTTP to a non-loopback host, never after
  a redirect, and never into events, the transcript, logs or errors.
- **Every run is capped.** The runner's options are closed: a turn limit and a token budget, each with a default
  named in one place in the runner. With no price from the service, the token budget is what bounds a run's spend.
- **A hosted service's failures map onto the contract as it stands:** authentication, rate limits (with
  `Retry-After`), server errors, network errors and timeouts are retried where retrying can help and reported as
  `retry` events. Refusals, a context-length error, an exhausted budget and a broken stream end in an `error`
  result that says which.
- **Usage and cost:** each request's usage is summed into the result's four token counters. `costUsd` is set only
  when the service reports a cost (some compatible hosts do); OpenAI reports none, so the result has no cost, as
  version 0 defines.
- **Tests:** deterministic tests against a fake endpoint, fixtures that pair recorded service output with the events
  it maps to, the runner conformance suite, and an opt-in live test against a real service, budget-capped and never
  run in CI.
- **troupe ships it:** `perform` knows the runner by name, passes it only the variables it needs, and the
  `troupe-run` bundle includes it.
- **The port's gaps it finds are filed, not worked around** (owner, 2026-11-04). This change builds on contract
  version 0 as it stands and uses its fields as they're defined. Each gap is filed as its own issue, proposed as its
  own change after #56's round of contract changes, and this runner adopts it then. The candidates so far are in
  the design (D12).

Out: each engine's native API (#56); the Responses API and other providers' own APIs; troupe storing secrets itself
(parked on #278); and the runtime's config, resolution and endpoint rules, which are #278's.

## Capabilities

### New Capabilities

- `openai-chat-runner`: the OpenAI-style runner: how it talks to a Chat Completions service, its tool loop, its
  options and limits, how the service's output and failures map onto run events, how the credential is handled,
  and how it's tested.

### Modified Capabilities

- `runs`: `perform` knows `openai-chat` by name, and passes it only the variables it needs.

## Impact

- **New:** `plugins/runner-openai-chat` (its package, published schemas, README, CHANGELOG and tests).
- **Core:** `troupe.core.interim` gains the runner's table entry. Nothing else in core changes: the runtime's
  resolution and its hand-off to the runner are #278's.
- **Workspace and releases:** the root `pyproject.toml` (workspace member, typing and lint paths, import contracts),
  `release-please-config.json` and its manifest, `packages/troupe-run` (the bundle pins it), and
  `scripts/check-paths.toml`.
- **Docs:** `plugins/README.md`, `contributing/runners.md` (a "Mapping an engine: Chat Completions" section) and the
  user docs on choosing a runner.
- **Dependencies:** none new. HTTP is the standard library's, behind one module.
- **troupe-run/infrastructure:** `oob/troupe-spec-purposes.json` records the new spec's Purpose, in a pull request
  that merges after this one.
- **Order:** #278 merges first. This change's tasks that touch the runtime's hand-off follow its final shape; if it
  lands differently from the shape assumed here (design D2), this change is updated before it's applied.
