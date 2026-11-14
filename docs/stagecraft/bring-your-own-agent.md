---
title: Bring your own agent
description: Using a different agent.
status: written
prerelease: true
---

troupe runs agents through **runners**. A runner starts an agent, passes it the actor's character and the run's direction, and reports what it
does back to troupe. Because troupe only ever talks to the runner, any agent can take part, whoever made it: you
swap the agent by swapping its runner, and your process stays the same.

## Runners today

troupe ships seven runners:

- **The scripted runner** plays a script instead of running an agent, so you can try troupe offline.
- **The Claude Code runner** runs [Claude Code](https://code.claude.com) with your existing login. It leaves out your
  Claude Code settings, hooks and MCP servers by default, so a run doesn't depend on whose machine it's on. It turns
  off Claude Code's automatic compaction, so a run whose conversation grows too long for the model fails rather than
  carrying on from a summary, unless the actor opts in to compaction
  ([When the context fills](../the-company/performances-and-runs.md#when-the-context-fills)). Its options choose the model, the budget and what the agent may do
  ([Define your own actor](../opening-night/first-performance.md#define-your-own-actor)).

- **The Ollama runner** runs a model on your own computer through [Ollama](https://ollama.com)'s own API, with
  troupe's own tool loop: the model asks for a file tool, and troupe carries it out, checked against the actor's
  effects. It needs no credential, costs nothing per run, and works offline. Where Ollama listens comes from a
  [runtime](runtimes.md), the built-in `ollama` for the Ollama on your machine (any host can be named: a run sends
  what the model reads there). The actor names the model, and its options the context window (`contextLength`)
  ([Try it with a model on your own machine](../opening-night/first-performance.md#try-it-with-a-model-on-your-own-machine)).

- **The OpenAI runner** runs an OpenAI model through its Responses API, or a model on any service that serves that API
  (local Ollama does), with troupe's own tool loop, checked against the actor's effects. Its service comes from a
  [runtime](runtimes.md), and its key from your environment, never from config. A run costs money on OpenAI, within
  the limits its options set (`maxTurns`, `maxTotalTokens`)
  ([Try it on OpenAI](../opening-night/first-performance.md#try-it-on-openai)).

- **The LM Studio runner** runs a model in [LM Studio](https://lmstudio.ai) on your own computer, through LM Studio's
  own client library: the library runs the model's rounds, and troupe carries out each tool call it asks for, checked
  against the actor's effects. It needs no credential and costs nothing per run. It comes with
  `troupe-run[lm-studio]` ([Install](../opening-night/install.md#runners-that-come-as-extras)), and LM Studio's server
  must be running with Require Authentication off. Where LM Studio listens comes from a [runtime](runtimes.md), the
  built-in `lm-studio` for the LM Studio on your machine. The actor names the model, and its options the limits
  (`maxTurns`, `maxTotalTokens`) and the context length (`contextLength`).

- **The Anthropic runner** runs a model over the Anthropic Messages API: Claude's own API, or a local engine that
  serves it, such as LM Studio, with troupe's own tool loop, checked against the actor's effects. It comes with
  `troupe-run[anthropic]` ([Install](../opening-night/install.md#runners-that-come-as-extras)). Its service comes from
  a [runtime](runtimes.md): the built-in `anthropic` for Claude's API, with its key in `ANTHROPIC_API_KEY`, or one of
  your own at a local engine's server root. A run on Claude's API costs money, within the limits its options set
  (`maxTurns`, `maxTotalTokens`, `maxOutputTokens`); `contextWindow` names a local engine's window, since some cut a
  full context without saying so.

- **The mistralrs runner** runs a model inside its own process with
  [mistral.rs](https://github.com/EricLBuehler/mistral.rs): no server and no network, with troupe's own tool loop,
  checked against the actor's effects. It costs nothing per run.
  It comes with `troupe-run[mistralrs]` ([Install](../opening-night/install.md#runners-that-come-as-extras)). Its model
  is a GGUF file on your machine, which the built-in in-process [runtime](runtimes.md) `mistralrs` points at: set
  `TROUPE_RUNTIME_MISTRALRS_MODEL` to its absolute path. On a Mac, install troupe on a uv-managed Python. Its options
  include the context window (`contextLength`), which it keeps to on every computer.

You can write a runner for any agent today, and check it against the contract, but you can't run it with
`troupe perform` yet: until config names runners ([#60](https://github.com/troupe-run/troupe/issues/60)),
`perform` only knows the runners troupe ships with.

## The runner contract

A runner is a program, in any language, that speaks troupe's runner contract over its standard input and output:

- **JSON-RPC 2.0, one message per line.** Standard output carries the contract's messages and nothing else;
  standard error is yours, and troupe keeps it with the run.
- **troupe starts the conversation.** It sends `initialize`, then one `run/start` with the run's direction, the
  actor's character (when it has one), the workspace and your runner's options. One runner process serves one run.
- **The runner reports as the agent works,** with `run/event` notifications (such as `init` first and one `result`
  last) and the engine's own output as `run/transcript`, which troupe keeps out of git. A runner that drives an
  API, with no output of its own to pass on, labels each record as sent, received or a note of its own.
- **troupe ends it,** with `run/cancel` if you press Ctrl-C, and `shutdown` when the run's done.
- **Nothing in the contract belongs to one engine or vendor.** A runner maps its agent's output onto it.

Your runner publishes JSON Schemas for its own options and error codes, so troupe and editors can check them, and it
refuses an option it doesn't define rather than ignoring it.

The full contract, with every message and event, is in
[contributing/runners.md](https://github.com/troupe-run/troupe/blob/main/contributing/runners.md), and its schemas
are in [`protocol/schemas/runner/`](https://github.com/troupe-run/troupe/tree/main/protocol/schemas/runner/).

## Check your runner

troupe's conformance suite checks a runner against the contract: the handshake, refusing what it should, cancelling
and exiting, and a whole run. Give it your runner's command line and the options for a short run that succeeds:

```sh
TROUPE_CONFORMANCE_RUNNER='["my-runner"]' \
TROUPE_CONFORMANCE_OPTIONS='{}' \
uv run pytest packages/troupe/tests/test_runner_conformance.py -k environment
```

Run it from a clone of troupe ([Install](../opening-night/install.md#running-it-from-a-clone)).

## What's decided for later

- **A runner runs as its own process,** speaking JSON-RPC, whether troupe ships it or you do. Policy can say which
  ways of running plugins are allowed.
- **A Python SDK** will make plugins easier to write ([#58](https://github.com/troupe-run/troupe/issues/58)).
- **How config names, pins and fetches a runner you didn't ship** is open, in
  [#38](https://github.com/troupe-run/troupe/issues/38) and [#67](https://github.com/troupe-run/troupe/issues/67).
