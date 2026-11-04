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

Today the scripted runner is the only one that takes a runtime, for troupe's own tests. The runners for local models
and for OpenAI-style APIs use runtimes as they arrive.

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
