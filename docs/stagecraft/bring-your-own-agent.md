---
title: Bring your own agent
description: Using a different agent.
status: written
prerelease: true
---

troupe runs agents through **runners**. A runner starts an agent, passes it the instructions, and reports what it
does back to troupe. Because troupe only ever talks to the runner, any agent can take part, whoever made it: you
swap the agent by swapping its runner, and your process stays the same.

## Runners today

The only runner so far is the scripted runner, which plays a script instead of running an agent, so you can try
troupe offline. The runners planned next are one for Claude Code
([#55](https://github.com/troupe-run/troupe/issues/55)) and one for a model on your own computer
([#56](https://github.com/troupe-run/troupe/issues/56)).

You can write a runner for any agent today, and check it against the contract, but you can't run it with
`troupe perform` yet: until config names runners ([#60](https://github.com/troupe-run/troupe/issues/60)),
`perform` only knows the runners troupe ships with.

## The runner contract

A runner is a program, in any language, that speaks troupe's runner contract over its standard input and output:

- **JSON-RPC 2.0, one message per line.** Standard output carries the contract's messages and nothing else;
  standard error is yours, and troupe keeps it with the run.
- **troupe starts the conversation.** It sends `initialize`, then one `run/start` with the instructions, the
  workspace and your runner's options. One runner process serves one run.
- **The runner reports as the agent works,** with `run/event` notifications (such as `init` first and one `result`
  last) and the engine's own output as `run/transcript`, which troupe keeps out of git.
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

Run it from a clone of troupe ([Install](../opening-night/install.md#trying-it-before-a-release)).

## What's decided for later

- **A runner runs as its own process,** speaking JSON-RPC, whether troupe ships it or you do. Policy can say which
  ways of running plugins are allowed.
- **A Python SDK** will make plugins easier to write ([#58](https://github.com/troupe-run/troupe/issues/58)).
- **How config names, pins and fetches a runner you didn't ship** is open, in
  [#38](https://github.com/troupe-run/troupe/issues/38) and [#67](https://github.com/troupe-run/troupe/issues/67).
