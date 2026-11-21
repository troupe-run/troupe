# Design: conformance-runtime

## Context

See proposal.md for why. Today the env-driven test reads `TROUPE_CONFORMANCE_RUNNER` and `TROUPE_CONFORMANCE_OPTIONS`
with bare `json.loads` and calls `check_runner` with no runtime. `check_runner` already takes `runtime` (sent in every
`run/start`) and `credential` (masked in the whole run, which `run_actor` drives); the caller puts the value in the
runner command's environment as `TROUPE_RUNTIME_CREDENTIAL`, as perform does. troupe's own runners that need a runtime
use that from their own tests (`test_the_openai_style_runner_passes_every_check_given_a_runtime_naming_a_stand_in`).

A run gets its runtime from `troupe.core.runtimes.for_run`: built-in values, then the theatre's config, then
`TROUPE_RUNTIME_<NAME>_ENDPOINT`, `_MODEL` and `_CREDENTIAL_ENV`. It reads the credential's value from the environment
and refuses it unset, malformed, too short to mask, or over plain HTTP to a non-loopback host, never repeating the
value. Config checks a runtime entry with `troupe.core.config.kinds.runtime_problems` (the runtime schema, the name
rule, the in-process and endpoint rules).

## Goals / Non-Goals

**Goals:**
- One route for a runner author: the documented env-driven check, with the same runtime resolution and credential
  rules a real run has.
- No secret in any `TROUPE_CONFORMANCE_*` variable, in the test's output, or in an error.

**Non-Goals:**
- A command-line front end for the conformance suite (`troupe runner check` or similar). The docs keep pointing at the
  pytest invocation.
- Runner fit (`runtimes.refuse_unfit`): it judges against troupe's own runner registry, which an outside runner isn't
  in. The conformance checks themselves find a runner that can't use the runtime.

## Decisions

### D1. The runtime is a JSON object shaped like config's runtime, plus its name

`TROUPE_CONFORMANCE_RUNTIME='{"name": "my-service", "endpoint": "https://api.example.com/v1", "model": "small",
"credential": {"env": "MY_SERVICE_KEY"}}'`. Everything but `name` is exactly a runtime's entry in config
(`runtime.schema.json`), so what a runner author writes here is what their users will write with `troupe config set`.
The test builds `{"runtimes": {name: entry}}` as a theatre config, checks it with `runtime_problems`, and resolves it
with `for_run`, so built-ins, `TROUPE_RUNTIME_<NAME>_*` overrides and every credential refusal behave as in a run.
`{"name": "openai", "model": "..."}` uses the built-in's endpoint and credential; no built-in names a model.

Alternatives: separate variables (`TROUPE_CONFORMANCE_ENDPOINT`, `_MODEL`, `_CREDENTIAL_ENV`) would duplicate
`TROUPE_RUNTIME_<NAME>_*` and need their own checks; naming a runtime only (`TROUPE_CONFORMANCE_RUNTIME=openai`) can't
describe a runtime troupe doesn't build in, since `resolve` refuses a name that is neither built in nor in config, and
the check runs with no theatre. A JSON object matches the two variables the check already takes.

### D2. The credential goes to the runner as a run gives it

With a credential, the runner command's environment gets `TROUPE_RUNTIME_CREDENTIAL` and `check_runner` gets
`credential=` the value. The variable the runtime names isn't passed through: the runner environment is built from
`defaults.RUNNER_ENVIRONMENT` plus that explicit entry, as perform's is. Since `for_run` reads the value only from the
environment and refuses before returning, no runner starts with a bad credential.

### D3. The env-reading code lives in the test module

The variables exist only for the pytest invocation the docs give, so a helper in `test_runner_conformance.py` reads
them, and the env-driven test calls a function that takes the environment as a mapping, so tests drive it with a dict
rather than by changing `os.environ`. A malformed variable raises a `ConformanceSetupError` (a `ValueError`) naming
the variable, what it must hold and the fix; refusals from `for_run` are `TroupeError`s and pass through unchanged
(their codes and words are the runtimes spec's). No error-catalogue entry is added: these aren't troupe errors a
surface shows, they fail a test. Unset or empty means absent, as `for_run` reads variables.

A model must come from somewhere: `for_run` names `actors.<actor>.model` in its no-model fix, which means nothing here,
so the helper resolves the runtime first and, when nothing sets a model, refuses itself, naming the object's `model`
and `TROUPE_RUNTIME_<NAME>_MODEL`. The actor `for_run` is given is `conformance`; with the model checked first, no
other refusal of `for_run` names it.

### D4. check_runner masks every check's problem

Each check's problem can hold the runner's own words (`it refused run/start: <problem>`). `check_runner` passes each
problem through `Masker(credential).text`, as the whole run's already is through `run_actor`. With no credential the
masker changes nothing. This touches how results are reported, not what any check checks.

### D5. Proof against a real runner that needs a runtime

The env-driven path is tested end to end against the OpenAI-style runner and its stand-in, with `credential.env`
naming a variable in the test's environment mapping, asserting every check passes, the stand-in saw the key as the
bearer token, and no result holds the key. That is #299's own failing case (5 of 8 with `openai.no-runtime`).

## Risks / Trade-offs

- [Schema problems echo a bad value, such as a key put in `credential.env`] → test it; the config check's messages
  are written not to repeat values (#298), and the helper reports `Problem.rule` and `fix` only.
- [JSON in a shell variable is awkward to quote] → the docs show a worked example; it's the form the two existing
  variables already use.
- [`for_run`'s refusals mention `troupe config set` fixes] → its words name the runtime's variables and config paths,
  which are what an author would change; acceptable for a test's failure message.
