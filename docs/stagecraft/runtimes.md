---
title: Point actors at a service
description: Runtimes, the services runners talk to, and how their keys stay out of config.
status: written
prerelease: true
---

Some runners talk to a service: a model served on your machine, or a hosted API that needs a key. troupe calls that
service a **runtime**. You define it once, by name, and each actor that uses it names it. The runtime holds where the
service is (`endpoint`), the model to use when an actor doesn't choose one (`model`), and, if it needs a key, the
name of the environment variable the key is in (`credential.env`). Never the key itself.

The OpenAI runner needs a runtime: the built-in `openai`, or one of your own whose service serves OpenAI's Responses
API, such as local Ollama's under `/v1` (`http://127.0.0.1:11434/v1`, not the built-in `ollama`'s address). The
scripted runner takes one optionally, for troupe's own tests. The Ollama runner still takes its endpoint and model in
its own options, and moves to the `ollama` runtime next ([#289](https://github.com/troupe-run/troupe/issues/289)).

## The runtimes troupe knows

troupe has three built in:

| Runtime | Endpoint | Credential |
|---|---|---|
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `ollama` | `http://127.0.0.1:11434` | none |
| `lm-studio` | `http://127.0.0.1:1234/v1` | none |

None names a model: model names change too often for a default to stay right. `troupe config get --resolved` shows
what every runtime resolves to, and where each value came from. For one of them:

```sh
troupe config get --resolved runtimes.openai
```

```text
runtime openai
  endpoint: https://api.openai.com/v1 (from default)
  model: none (an actor's model, runtimes.openai.model or TROUPE_RUNTIME_OPENAI_MODEL sets one)
  credential: from OPENAI_API_KEY (named by default), not set
```

`set` or `not set` says whether the variable has a value in your environment. troupe never shows the value.

## Change a runtime for this theatre

Set any field, and the rest stay as they were. Config records the change, and `.troupe/runtimes/openai.yaml` shows
what you set, for review like any other config file:

```sh
troupe config set runtimes.openai.model=gpt-4.1-mini
troupe config set runtimes.openai.credential.env=MY_OPENAI_KEY
```

Define a service troupe doesn't know with its endpoint, and the rest as it needs:

```sh
troupe config set runtimes.office-llm.endpoint=https://llm.example.com/v1 runtimes.office-llm.model=llama3.3 runtimes.office-llm.credential.env=OFFICE_LLM_KEY
troupe config get --resolved runtimes.office-llm
```

An actor names its runtime, and can choose its own model:

```text
troupe config set actors.reviewer.runtime=openai actors.reviewer.model=gpt-4.1
```

## Change it for yourself

Your environment overrides the theatre's config, for you alone, without a change anyone else sees:

| Variable | Overrides |
|---|---|
| `TROUPE_RUNTIME_<NAME>_ENDPOINT` | the endpoint |
| `TROUPE_RUNTIME_<NAME>_MODEL` | the model, for every actor on the runtime, the actor's own included |
| `TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV` | which variable the key is read from |

`<NAME>` is the runtime's name in capitals, with `-` as `_`: `TROUPE_RUNTIME_LM_STUDIO_MODEL`. An empty variable
counts as unset. One that's set but malformed, such as an endpoint that isn't a URL, stops the command and names it,
rather than quietly using another value.

## Price a model, for an estimated cost

Claude Code reports what a run cost. OpenAI reports only the tokens it used, so without a price an OpenAI run has no
cost. Give a model a price, in US dollars per million tokens of each kind, and a runner whose service reports no cost
sends an **estimate**, marked as one (`estimatedCostUsd` in the run's result, never `costUsd`):

```sh
troupe config set 'runtimes.openai.prices.gpt-5-mini={"input": 0.25, "cacheRead": 0.025, "cacheWrite": 0, "output": 2}'
```

The rates are `input`, `output`, `cacheRead` (input read from the service's prompt cache) and `cacheWrite` (input
written to it). `input` and `output` are required. Set the cache rates too, with `0` for one the service doesn't
charge: OpenAI runs nearly always read from and write to the cache, and **a run gets no estimate when it used a kind
of token the price has no rate for**, or when the price has a rate for a kind the service didn't count. troupe leaves
the cost out rather than guess. Copy the rates from the service's price list; troupe ships none, so they never go
stale behind your back.

A price applies to the model a run uses, matched exactly: `gpt-5-mini` doesn't price `gpt-5-mini-2026-01-01`. A
model priced in config but overridden by `TROUPE_RUNTIME_<NAME>_MODEL` gets the overriding model's price, or none.
No variable sets a price. `troupe config get --resolved` and `troupe perform --rehearse` show the price that applies,
and every run records the price it used, so an estimate can always be checked against its tokens.

A model whose name holds a dot, like `gpt-4.1`, can't be named in a `config set` path, since dots separate the keys
([#303](https://github.com/troupe-run/troupe/issues/303)). Set the runtime's whole price list instead, which replaces
it, so include every model:

```sh
troupe config set 'runtimes.openai.prices={"gpt-4.1": {"input": 2, "cacheRead": 0.5, "cacheWrite": 0, "output": 8}, "gpt-5-mini": {"input": 0.25, "cacheRead": 0.025, "cacheWrite": 0, "output": 2}}'
```

## Keys stay in your environment

Config is committed, and travels with every clone. So it only ever names the variable a key is in. troupe reads the
value from your environment when a run starts and gives it to the runner, and nowhere else:

- **Not written anywhere troupe keeps:** not config's events or files, not the run's events, transcript or standard
  error, and not in an error. If a runner sends the key back, troupe records `[credential]` in its place.
- **Not sent in the clear:** a key goes over `https`, or plain `http` only to this machine (`localhost`, `127.0.0.1`,
  `[::1]`).
- **Not too short to hide:** a key under 8 bytes is refused, since troupe couldn't tell it apart from ordinary text.
  A service that needs no key, like a local model, needs no credential at all.

A run whose key isn't set stops before it starts, naming the variable to set.

## What a theatre's config can still choose

Because config is shared, a theatre's config, or one merged in from someone else's branch, can choose **where** your
key goes (the endpoint) and **which** of your variables is sent (`credential.env`). troupe doesn't refuse either yet:
limiting both is policy's job, and it's planned. Until then:

- `troupe config get --resolved` and `troupe perform --rehearse` show the endpoint and the variable, and whether each
  came from troupe, the theatre's config or your environment, before anything runs.
- Every run records them, with where each came from.
- Review changes to `.troupe/runtimes/` in a diff as you would code, and set `TROUPE_RUNTIME_<NAME>_ENDPOINT`
  yourself when you want to be sure where a key goes.
