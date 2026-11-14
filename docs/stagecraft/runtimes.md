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
Ollama runner needs one too: the built-in `ollama`, or one of your own for an Ollama elsewhere, whose endpoint is
Ollama's own address with no path, such as `http://gpu-box.local:11434`. It refuses a runtime with a credential,
since Ollama takes none. An Ollama actor still holding `model` or `endpoint` in its options, as early versions of
`troupe init --audition` wrote it, is refused with the one `troupe config set` that moves them. The Anthropic runner
needs one too: the built-in `anthropic`, Claude's own API, or one of your own for a local engine that serves the Anthropic
Messages API, such as LM Studio's or Ollama's server root. The scripted runner takes one optionally, for troupe's own
tests.

## The runtimes troupe knows

troupe has three built in:

| Runtime | Endpoint | Credential |
|---|---|---|
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `anthropic` | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` |
| `ollama` | `http://127.0.0.1:11434` | none |

Which runner each fits:

| Runtime | `openai` runner | `anthropic` runner | `ollama` runner | `scripted` runner |
|---|---|---|---|---|
| `openai` | yes | no: it's OpenAI's | no: it has a credential, and Ollama takes none | yes |
| `anthropic` | no: its endpoint has no path, so it isn't the Responses API | yes | no: it has a credential, and Ollama takes none | yes |
| `ollama` | no: its endpoint has no path, so it isn't the Responses API | no: it's Ollama's | yes | yes |

Each built-in fits only the runner it's made for (and the scripted runner, which takes any), even where its address has
the shape another needs, since two engines can look alike at the same address. A runtime of your own fits by the rules
alone: the OpenAI runner needs an endpoint with a path, the Ollama runner one with no path and no credential, and the
Anthropic runner any endpoint (its path, if it has one, must not end in `/v1`, which the runner adds itself). Config
refuses an actor on a runtime that doesn't fit, naming the runtimes that do, and so does `troupe perform`
(`runtime.unfit`) when a `TROUPE_RUNTIME_` variable makes one stop fitting.

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

To run the OpenAI runner on a server on your own machine that serves an OpenAI-compatible API, define a runtime of
your own at that API's `/v1`:

```sh
troupe config set runtimes.local-openai.endpoint=http://127.0.0.1:8080/v1
```

The Anthropic runner reaches a local engine that serves the Anthropic Messages API through a runtime of your own at
the engine's server root, not a built-in. For LM Studio, define the runtime:

```sh
troupe config set runtimes.lm-studio-messages.endpoint=http://127.0.0.1:1234
```

Then point an actor on the `anthropic` runner at it, with a model LM Studio has:

```text
troupe config set actors.lead.runtime=lm-studio-messages actors.lead.model=google/gemma-4-e4b
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

`<NAME>` is the runtime's name in capitals, with `-` as `_`: `TROUPE_RUNTIME_LOCAL_OPENAI_MODEL`. An empty variable
counts as unset. One that's set but malformed, such as an endpoint that isn't a URL, stops the command, naming the
variable and what it takes, rather than quietly using another value. The error never repeats what the variable holds,
in case it's a key put there by mistake.

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

A model whose name holds a dot, like `gpt-4.1`, goes in square brackets in the path, so its dot isn't read as one
between keys. Keep the argument quoted: zsh reads unquoted brackets as a pattern and stops. This sets the one price,
beside the others:

```sh
troupe config set 'runtimes.openai.prices[gpt-4.1]={"input": 2, "cacheRead": 0.5, "cacheWrite": 0, "output": 8}'
```

[The CLI reference](../prompt-book/cli.md) says how a config path is written.

## Keys stay in your environment

Config is committed, and travels with every clone. So it only ever names the variable a key is in. troupe reads the
value from your environment when a run starts and gives it to the runner, and nowhere else:

- **Not written anywhere troupe keeps:** not config's events or files, not the run's events, transcript or standard
  error, and not in an error. If a runner sends the key back, troupe records `[credential]` in its place.
- **Not sent in the clear:** a key goes over `https`, or plain `http` only to this machine (`localhost`, `127.0.0.1`,
  `[::1]`).
- **Just the key:** a key may hold only visible ASCII characters. One holding a space, a line ending left from the
  file it was read from, or a letter outside ASCII is refused before any runner gets it, since a request header can't
  carry it.
- **Not too short to hide:** a key under 8 bytes is refused, since troupe couldn't tell it apart from ordinary text.
  A service that needs no key, like a local model, needs no credential at all.

A run whose key isn't set stops before it starts, naming the variable to set. When
`TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV` chose that variable, the error names `TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV`
instead, and never repeats what it holds, in case it's a key put there by mistake. `troupe config get --resolved`
does the same:

```text
  credential: from the variable TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV names (named by env), not set
```

## What a theatre's config can still choose

Because config is shared, a theatre's config, or one merged in from someone else's branch, can choose **where** your
key goes (the endpoint) and **which** of your variables is sent (`credential.env`). troupe doesn't refuse either yet:
limiting both is policy's job, and it's planned. Until then:

- `troupe config get --resolved` and `troupe perform --rehearse` show the endpoint and the variable, and whether each
  came from troupe, the theatre's config or your environment, before anything runs.
- Every run records them, with where each came from.
- Review changes to `.troupe/runtimes/` in a diff as you would code, and set `TROUPE_RUNTIME_<NAME>_ENDPOINT`
  yourself when you want to be sure where a key goes.
