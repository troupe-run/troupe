# Proposal: runtime, credential and actor-file checks

## Why

Five gaps found while building runtimes (#278, #289, #298) let a run be refused late, after its start is recorded, or
let troupe show or hide the wrong thing about a runtime:

- **#334**: config accepts an actor whose runner can't use its runtime (an `ollama` actor on `openai` or `lm-studio`,
  an `openai` actor on the built-in `ollama`), and its "needs a runtime" error suggests such pairs. Each fails only
  after a run is started and recorded.
- **#329**: a credential holding a character an HTTP header can't carry, such as `€`, passes troupe's check, and the
  run fails late as a network error instead of being refused with `runtime.credential-malformed`.
- **#323**: an endpoint refused for holding user info (`https://user:password@host/...`) is repeated, password included,
  in the SDK's `runner.invalid-params` refusal, which every runner on the SDK shares. (The environment variable's
  refusal, the other path the issue found, stopped repeating its value in #298, commit `610096d9`; this change adds
  the end-to-end test the issue asks for and checks every other place an endpoint is echoed.)
- **#306**: `troupe config get --resolved` prints a credential variable's name taken from
  `TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV` as it is, though a key put there by mistake passes for a name. #298 already
  keeps such a name out of every refusal.
- **#288**: an actor's file holds only `runner`, `options` and `expect`, so a change to its `effects`, `workspace`,
  `runtime` or `model` shows nothing in the diff a reviewer reads.

They share code (the runner table, `core/runtimes.py`, the SDK's credential and message checks, config's actor rules
and projection), so one change and one pull request closes all five.

## What Changes

- **Runtime fit (#334).** troupe's runner table (`troupe.core.interim.RUNNERS`, the table #333 / PR #338 extends with
  `in_extra`) says, for each runner that takes a runtime, what runtime fits it: whether the runner sends a credential,
  and whether its endpoint must have a path, must have none, or either. One function judges a runtime's fields
  against it.
  - Config refuses an actor whose runtime doesn't fit its runner, naming the actor, the runtime, why, and the runtimes
    that fit, judged from the built-in and theatre values. A change to a runtime that makes an actor on it unfit is
    refused too, naming the actor.
  - The "needs a runtime" error, and the "no such runtime" error, list only the runtimes that fit the actor's runner.
  - Perform applies the same rule to the runtime as resolved, environment included, and refuses with a new code,
    `runtime.unfit`, before anything is recorded and before any runner starts.
  - The OpenAI runner refuses an endpoint with no path (`openai.no-runtime`, where `runtime.endpoint`), so config and
    the runner agree. Every OpenAI-style service troupe knows of serves its API under a path such as `/v1`.
- **Credential characters (#329).** A credential's value may hold only visible ASCII (`!` to `~`). The one definition,
  `troupe_plugin_sdk.credential.well_formed`, narrows to that, so core's `runtime.credential-malformed` and the OpenAI
  runner's `openai.malformed-credential` both refuse `sk-test-€abcdefgh` before anything is sent. Their messages and
  the specs say "a character a request header can't carry" instead of "whitespace or a control character".
- **Endpoint user info (#323).** The SDK's refusal of a `run/start` whose `runtime.endpoint` doesn't match the endpoint
  pattern names the field and what an endpoint must be, never the value. The OpenAI runner's own endpoint refusal
  stops quoting an endpoint that holds user info. A canary test covers each path that can refuse such an endpoint:
  `config set`, the environment variable through the CLI's standard error and client message, and `run/start`
  through a runner's error.
- **Resolved credential names (#306).** `config get --resolved` (and anything showing a runtime resolved without
  starting a run) shows a credential variable's name only when it comes from the theatre's config or a built-in
  runtime. When `TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV` set it, it shows that variable as `namedBy` and whether the
  named variable is set, and holds no part of the name. A run's start record and a rehearsal keep the name, since a
  run gets that far only when the name is a set variable holding a well-formed key.
- **Actor files (#288).** An actor's file holds every field the actor schema defines, in the schema's order, the
  character excepted (it's the `.md` file). A test holds the file's field order to the schema, and another checks a
  written file holds every field config set. An existing file troupe wrote gains the fields on the next flush.

No requirement is removed, and nothing here is **BREAKING** for a released surface: `config get --resolved`'s result
schema gains a second form for `credential.env`, and the error catalogue gains `runtime.unfit` (pre-1.0, no
compatibility forms).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runtimes`: an actor's runtime must fit its runner, in config and at perform (`runtime.unfit`); the "needs a
  runtime" list holds only runtimes that fit; a credential holds only visible ASCII; `config get --resolved` names a
  credential variable from the environment by `namedBy`; a refused endpoint's user info appears nowhere troupe writes.
- `openai-runner`: an endpoint with no path is refused; a credential holding anything but visible ASCII is refused.
- `plugin-sdk`: the SDK's refusal of an endpoint that doesn't match its pattern never repeats the value; its
  credential check is visible ASCII.
- `config-files`: an actor's file holds every field the actor schema defines, the character excepted, in schema order.

## Impact

- **Code:** `packages/troupe/src/troupe/core/interim.py` (runner table), `core/runtimes.py` (fit, `for_run`,
  `Resolved.to_data`), `core/config/kinds.py` (actor rules), `core/config/projection.py` (`FIELD_ORDER`),
  `core/runs/perform.py`, `cli/runtimes.py`; `packages/troupe-plugin-sdk/src/troupe_plugin_sdk/credential.py` and
  `messages.py`/`runner.py`; `plugins/runner-openai/src/troupe_runner_openai/service.py` and `runtime.py`.
- **Schemas:** `error.schema.json` gains `runtime.unfit` (both copies: `protocol/schemas/` and the packaged one);
  `runtime.schema.json#/$defs/resolved` lets `credential.env` be `{namedBy, source: "env"}`.
- **Docs:** `contributing/runners.md` (a runner's runtime fit), the runtimes user docs where they describe credentials
  or `--resolved`.
- **Coordination:** PR #338 (#333, `runner-extras`, session `track-b-26-333`) adds `in_extra` to the same `Runner`
  dataclass and a new code to the same error catalogue. This change adds its field after `in_extra` in the same style,
  and rebases onto main once #338 merges.
- **Out of scope:** restricting which hosts or endpoints are allowed (policy, #286); checking at run time that a
  service is what its endpoint claims (the runners' preflights); the run-started record's credential name.
- No spec is added or removed and no Purpose changes, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json`
  needs no update.

Issues: troupe-run/troupe#323, #334, #329, #306 and #288. The pull request closes all five.
