# Proposal: runtimes

Issue: [troupe#278](https://github.com/troupe-run/troupe/issues/278). It blocks #277 (Ollama, split from #56) and
#162 (the OpenAI-style runner).

## Why

0.2.0's two new runners talk to a service: the Ollama runner to a local engine, the OpenAI-style runner to a hosted API
that needs a key. Each needs an endpoint and a model, and #162 also needs a credential. They should come from one config
structure, defined once and looked up by name, not from each runner's options (owner, 2026-11-04, on #162). The
credential has to reach the runner without being written anywhere troupe keeps, since config, events and transcripts
live in the repository and travel with it.

## What Changes

- **A new config kind, `runtimes.<name>`**: a service a runner talks to, with an `endpoint`, a default `model` and an
  optional `credential.env`, the **name** of the environment variable that holds the key, never the key. It's
  projected to `.troupe/runtimes/<name>.yaml` like an actor, with its own schema.
- **Built-in runtimes as named defaults in one place:** `openai` (OpenAI's API, credential from `OPENAI_API_KEY`),
  `ollama` and `lm-studio` (their default local addresses, no credential). None names a model, since a built-in model
  would go stale.
- **An actor names its runtime** (`actors.<name>.runtime`) and may override its model (`actors.<name>.model`). troupe's
  runner table says whether a runner takes a runtime; config refuses a runtime the runner can't use, and an actor
  without one when its runner needs one.
- **A runtime's values are resolved from troupe's defaults, then the theatre's config, then the person's environment**
  (`TROUPE_RUNTIME_<NAME>_ENDPOINT`, `_MODEL`, `_CREDENTIAL_ENV`), each overriding the one before, and each value
  carries the source it came from, as settings and policy do. An actor's model sits above the runtime's config and
  below the environment. A malformed value is an error naming the variable or path, never a fall-through.
- **`troupe config get --resolved [runtimes[.<name>]]`** shows each runtime's resolved values and their sources,
  whether its credential's variable is set (never its value). A rehearsed `perform` shows the runtime the run would
  use. A `troupe runtimes` command is left for later (D9).
- **Runner contract change (a protocol change):** `run/start` gains an optional `runtime` object: name, endpoint,
  model, and whether there's a credential. The credential's value reaches the runner only in its environment, as
  `TROUPE_RUNTIME_CREDENTIAL`, never in `run/start` (which troupe records). This is the one contract change in this
  change's pull request.
- **troupe masks the credential's value** in everything it keeps from a run: run events, the transcript, the kept
  standard error, error messages and details. The run's start records the runtime's resolved values and sources, and
  the credential's variable name, not its value.
- **A credential is sent only over HTTPS, or to a loopback address.** A credential shorter than 8 bytes is refused,
  since it can't be masked safely.
- **The scripted runner takes an optional runtime,** with steps that check what it received and that echo the
  credential back, so tests can show troupe masks it.
- **A test that a known credential appears nowhere troupe writes:** config events, projected files, run events,
  transcripts, kept standard error, errors, rehearsals and `config get`.

**Accepted risks, on record (owner, 2026-11-04; design D7):** config is committed, so a theatre's config can choose
both the endpoint a credential goes to and which environment variable is sent. troupe doesn't refuse either for now:
policy will limit the endpoints and the variables later. The run's start records where each came from.

Out: troupe storing secrets itself (parked on #278); each runner's own use of a runtime (#277, #162); container
credentials (#11); policy limits on endpoints and credential variables (a follow-up issue, filed by this change).

## Capabilities

### New Capabilities

- `runtimes`: what a runtime is, the built-in runtimes, how its values are resolved and shown with their sources, how
  an actor names one, and how a run's credential is handled: by reference, masked, and only over a safe transport.

### Modified Capabilities

- `config`: the actor gains `runtime` and `model`; config has a second kind; `config get` gains `--resolved`.
- `config-files`: runtimes are projected to `.troupe/runtimes/<name>.yaml`, a known kind with its schema.
- `runner-protocol`: `run/start` carries the runtime; the credential is the one thing a runner takes outside it, in
  its environment; the transcript a runner sends is kept with the credential masked.
- `runs`: perform resolves the actor's runtime, records it in the run's start, passes the credential's value to the
  runner, masks it in what it keeps, and shows the runtime in a rehearsal.
- `scripted-runner`: an optional runtime, a step that checks it and a step that echoes the credential.

## Impact

- **Protocol:** `config/runtime.schema.json` (new), `config/actor.schema.json` (`runtime`, `model`),
  `runner/run-start.schema.json` (`runtime`), `events/run-started.schema.json` (`runtime`), the client's config-get
  and perform rehearsal schemas, and new error codes in the catalogue. A protocol minor release (pre-1.0).
- **Core:** a runtimes module (built-ins in `defaults.py`, resolution, masking), `config/kinds.py`, the projection,
  `interim.py` (each runner says whether it takes a runtime), `runs/perform.py`, `runners/host.py` (masking), the
  config-get command, and the SDK's `run/start` types.
- **Plugins:** the scripted runner's options, steps and schemas. The Claude Code runner is unchanged: it takes no
  runtime.
- **CLI and docs:** `--resolved` on `config get`, `docs/prompt-book` (generated reference), a stagecraft page on
  runtimes and credentials, and `contributing/runners.md` (the hand-off).
- **troupe-run/infrastructure:** `oob/troupe-spec-purposes.json` records the new `runtimes` spec's Purpose, in a pull
  request that merges after this one.
- **Order:** #162's design (D2) assumed this hand-off; it's updated if what lands differs. #277's runner takes its
  endpoint and model in its options today, and moves to a runtime in a follow-up of its own.
