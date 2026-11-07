# Proposal

## Why

The Ollama runner ([#277](https://github.com/troupe-run/troupe/issues/277)) merged with `endpoint` and `model` in its
own options, before runtimes existed. #278 ([#287](https://github.com/troupe-run/troupe/pull/287)) made runtimes the
one place a service is defined, for every runner that talks to one (owner, 2026-11-04, on #162), and the OpenAI
runner already takes its service from one. Until the Ollama runner moves too, it's the one runner whose service lives
in its options. So its endpoint can't be overridden from the person's environment, isn't shown by
`troupe config get --resolved`, and isn't recorded in a run's start. Issue:
[#289](https://github.com/troupe-run/troupe/issues/289).

## What Changes

- **BREAKING** (pre-release, unreleased 0.2.0 runner): the `ollama` runner **requires a runtime**. troupe's runner
  table says so, and config refuses an `ollama` actor that names none. An actor names the built-in `ollama` runtime
  (`http://127.0.0.1:11434`) or one of its own, and its model comes from the runtime's resolution: the person's
  `TROUPE_RUNTIME_<NAME>_MODEL`, then the actor's `model`, then the runtime's.
- **BREAKING**: the runner reads its endpoint and model from `run/start`'s `runtime`, and nowhere else. `endpoint` and
  `model` leave its options and its published options schema, and the runner holds no default endpoint. Its other
  options (`maxTurns`, `contextLength`, `temperature`, `seed`, `think`) stay. A `run/start` with no runtime is refused
  with `ollama.no-runtime`.
- The runner still checks the endpoint it's given against its own rules (no path, and a port and host a connection
  can use), now refused as `ollama.invalid-runtime`, naming `runtime.endpoint`. A runtime with a
  credential is refused with `ollama.credential-unsupported`, since the runner sends no credential.
- An actor recorded with `options.model` or `options.endpoint` on the `ollama` runner is refused by config, wherever
  config is checked (any `config set`, and `perform`), with a rule that says the value moved to the actor's runtime,
  and a fix that is the one `troupe config set` that moves it.
- The Ollama audition (`troupe init --audition --runner ollama`) writes `runtime: ollama` and `model`, rather than
  `options.model`, and its note reads the actor's `model`.
- The Ollama runner's errors that point at its endpoint (unreachable, invalid) name the runtime's config path and its
  `TROUPE_RUNTIME_<NAME>_ENDPOINT` variable as the way to change it.
- Docs: the Ollama runner's README, `docs/stagecraft/runtimes.md` (drop its note that the runner still takes its
  options), and the pages that describe the Ollama actor's options.

Out of scope, per the issue: the built-in `ollama` runtime itself (#278 added it), and restricting endpoints (policy's
job; #286 for credentials, and Ollama has none). Sending a credential to an Ollama service that takes one (such as
Ollama's own cloud API) isn't asked for; this change refuses it rather than dropping it, and it can be a follow-up.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `ollama-runner`: the service comes from the run's runtime; `model` and `endpoint` leave the options; the endpoint
  rules apply to the runtime's endpoint; a runtime with a credential is refused; the init event and errors name the
  runtime; the conformance suite runs it with a runtime.
- `runtimes`: options a runner has moved to its runtime are refused with the `config set` that moves them; an
  `ollama` actor must name a runtime.
- `runs`: the runner table says `ollama` requires a runtime.
- `config`: the Ollama audition names the `ollama` runtime and sets the actor's `model`, with no options.

## Impact

- `plugins/runner-ollama/`: `options.py`, `defaults.py` (no `DEFAULT_ENDPOINT`), `runner.py` (read the runtime,
  refusals), a runtime module, `schemas/options.schema.json` and `schemas/errors.schema.json`, `tools/capture_ollama.py`,
  fixtures' provenance, tests and README.
- `packages/troupe/`: `core/interim.py` (runner table), `core/config/kinds.py` (moved-option problem),
  `core/audition.py`, `cli/init.py`, and tests that point an Ollama run at a stand-in through `options.endpoint`
  (`test_perform_ollama`, `test_ollama_host`, `test_cli_init`, `test_runner_conformance`, config tests).
- Docs: `docs/stagecraft/runtimes.md`, `docs/stagecraft/bring-your-own-agent.md`,
  `docs/opening-night/first-performance.md`, and any generated config-schema page.
- No protocol change: `run/start` already carries `runtime`, and the run's start already records it.
- No spec Purpose changes, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json` is untouched.
