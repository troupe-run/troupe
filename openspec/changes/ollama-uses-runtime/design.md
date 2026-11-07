# Design

## Context

See proposal.md, Why. What's there now:

- **Runtimes** (#278, archived `runtimes`): `core/defaults.py` holds the built-in `ollama` runtime
  (`http://127.0.0.1:11434`, no credential). `core/runtimes.py` resolves a run's runtime (env → actor → theatre for the
  model; env → theatre → default for the endpoint). `perform` records it in the run's start and sends it as
  `run/start`'s `runtime` (`name`, `endpoint`, `model`, `credential`), with the credential's value only in
  `TROUPE_RUNTIME_CREDENTIAL`.
- **Runner table** (`core/interim.py`): `ollama` has `runtime="none"` (the default) and an empty environment, so config
  refuses an `ollama` actor that names a runtime.
- **Config checks** (`core/config/kinds.py`): `actor_problems` checks options against the runner's published options
  schema, so an unknown option is "there's no such field … Unset it." `refuse_unrecordable` checks the **whole** config
  after every change, and `check_actor` checks the actor at perform.
- **The Ollama runner** (`plugins/runner-ollama/`): `options.py` parses `model` (required) and `endpoint`
  (default `DEFAULT_ENDPOINT` in `defaults.py`), with a strict endpoint regex: no path, a valid port, and host name
  parts of 1 to 63 characters. `runner.py` preflights against `options.endpoint` and `options.model`.
- **The OpenAI runner** already reads its runtime through one module, `runtime.py` (`from_run_start`,
  `RuntimeRefusedError`), which is the shape to follow.

## Goals / Non-Goals

**Goals:**
- One source for the Ollama runner's service: `run/start`'s `runtime`.
- A theatre that holds an old Ollama actor gets a refusal it can act on with one copy-paste, and never a dead end.

**Non-Goals:**
- Sending a credential to an Ollama service (see D3).
- Accepting a base path in an Ollama endpoint, such as Ollama behind a reverse proxy at `/ollama` (see D4).
- A general "moved option" mechanism for other runners. Only `ollama` has moved options, and the table in D5 is where
  a later one would go.

## Decisions

### D1. The runner table says `ollama` requires a runtime; its environment stays empty

`RUNNERS["ollama"]` gets `runtime="required"`. Its environment stays empty: the runner still reads no variable, not
`OLLAMA_HOST`, and not proxy variables. This is unchanged from local-model-runner D10, and a local Ollama needs none.
If the runtime has a credential, perform still sets `TROUPE_RUNTIME_CREDENTIAL` for the runner (the host does that for
every runner). The runner refuses the run without reading it (D3).

*Alternative:* `optional`, falling back to the built-in when an actor names none. That would bring back an implicit
default the actor's config doesn't show, so `config get` and the run's start couldn't explain where the endpoint came
from. It's the gap the issue is about.

### D2. A `runtime.py` in the runner, like the OpenAI runner's

A module `troupe_runner_ollama/runtime.py` is the one place the runner reads its runtime. `from_run_start(params)`
returns a frozen `Runtime(name, endpoint, model)` or raises `RuntimeRefusedError(code, where, problem, fix)`:

- `params.runtime is None` → `ollama.no-runtime`, where `runtime`.
- `params.runtime.credential` → `ollama.credential-unsupported`, where `runtime.credential` (D3).
- The endpoint fails the runner's rules → `ollama.invalid-runtime`, where `runtime.endpoint` (D4).

The model needs no check of its own: the SDK's `RunStartRuntime` already holds it to the protocol's model pattern (no
control characters, not empty), so a bad one is `runner.invalid-params`. Fixes that name config use the runtime's name:
`runtimes.<name>.endpoint`, and `TROUPE_RUNTIME_<NAME>_ENDPOINT` with `<NAME>` in capitals and `-` as `_`, the same
rule `core/runtimes.py` uses. The runner works it out itself, since it can import nothing of core's. A test checks it
matches core's rule for the built-in names and a hyphenated one.

`Options` loses `model` and `endpoint`. The runner passes the `Runtime` beside the `Options` to preflight and to the
conversation, which take `endpoint` and `model` from it. `DEFAULT_ENDPOINT` leaves `defaults.py` and the README's
limits table. The built-in runtime in core is now the only place that address is written down (spec: "no endpoint or
model SHALL be written in the runner").

The order of refusals in `run/start`: params (`runner.invalid-params`), then options, then runtime, then preflight.
Options come before runtime because an old `run/start` holding `options.model` gets the clearer `unknown-option`,
naming `model`, before `no-runtime`.

### D3. A runtime with a credential is refused, not ignored

Ollama itself takes no credential. A runtime with one means someone expects it to be sent: an Ollama behind an
authenticating proxy, or Ollama's cloud API. Dropping it quietly would turn into a 401 from the service and a confusing
`ollama.unreachable` or HTTP error, which is the "malformed input falls through" shape the project rules out. Refusing
with `ollama.credential-unsupported` names the problem. Sending it, as `Authorization: Bearer`, the way the OpenAI
runner does, would add masking, the insecure-endpoint check and the credential-mismatch rules to this runner. That's
real scope nobody has asked for, so it's left for a follow-up issue if someone wants it.

*Alternative:* config or perform refuses an `ollama` actor whose runtime has a credential, before anything is
recorded. That's better for the person, but it needs a "takes a credential" column in the runner table and a check
across kinds. The runner's refusal is enough while no one does this, and the follow-up can move it.

### D4. The endpoint rules stay the runner's, and apply to the runtime's endpoint

A runtime's endpoint may have a path (config allows `https://host/v1` for OpenAI-style services). The Ollama runner
builds `/api/...` from the endpoint's root and still refuses a path, now as `ollama.invalid-runtime`. That's no
looser and no stricter than today, and the common mistake it catches is pointing an `ollama` actor at an
OpenAI-compatible `…/v1` address. The fix says so: the native API is at the root, and the `/v1` address is for the
`openai` runner. The rule's code and `details.where` change. Its regex and messages move from `options.py` to
`runtime.py` unchanged apart from the path names, so the existing property tests carry over.

*Alternative:* accept a path as a prefix (`https://host/ollama` → `https://host/ollama/api/chat`). It's reasonable
for reverse proxies, but it widens what the runner accepts, and nobody has asked for it.

### D5. Moved options are a named problem, with a computed fix, in `kinds.py`

A table in core, `MOVED_OPTIONS = {"ollama": ("model", "endpoint")}`, sits beside the runner table in `interim.py`.
`actor_problems` checks it before the options schema. For each moved key the actor's options hold, it reports a
`Problem` at `actors.<name>.options.<key>` with the rule "<key> moved to the actor's runtime (the ollama runner reads
its service from a runtime now)". The schema's own "no such field" problem for that key is left out, and so is the
missing-runtime problem for the same actor, so the person sees one rule with one fix.

The fix is one command, worked out from the actor and the config:

- **runtime**: chosen by endpoint, and never by editing a runtime that exists, so moving one actor can't repoint
  another. The endpoint the actor ran against is `options.endpoint`, or the built-in `http://127.0.0.1:11434` when
  it set none. The fix keeps the actor's own `runtime` if it names one whose endpoint is that. Otherwise it picks
  the first runtime whose endpoint is that, `ollama` first, then the rest by name. Otherwise it defines a new runtime
  named after the actor (`runtimes.<actor>.endpoint=<endpoint>`), or `<actor>-2`, `-3` and so on when that name is
  taken, with the base cut so the name fits 64 characters. Endpoints are compared as config and troupe's defaults
  resolve them, ignoring the environment, which is the person's and not the theatre's. They're compared after the
  runner's own normalising (no trailing `/`).
- **model**: the actor's `model` if it sets one (it wins at run time anyway, spec: runtimes), else `options.model`.
  Left out when neither is set; the runtime may name one.
- **options**: the options without the moved keys, written as compact JSON in one group set
  (`'actors.<n>.options={...}'`, or `{}`). Setting a group replaces it whole (`changes.set_value`), so the moved keys
  go in the same change. That's what makes one command enough: `config set` and `config unset` are separate commands,
  and each is checked against the whole config, so no sequence of two could pass through a valid state.

Quoting follows the existing fixes (`_expect_problems`): POSIX single quotes around a value with JSON in it. A test
runs each fix through the CLI exactly as given (split with `shlex`) and checks config is then valid. That's the only
claim the spec makes about the fix.

*Alternatives considered:*
- **Tolerate the old options at config time and refuse only at perform.** Unrelated config changes would keep working,
  but it loosens a closed schema for one runner and still leaves the actor broken. And the whole-config check exists
  so config never records a state that breaks a rule.
- **Migrate silently**, rewriting the actor on read. It's a projection that disagrees with the events, and it's
  against "never rewrite what the user didn't ask to change".
- **Override `runtimes.ollama.endpoint`** for a non-default endpoint. It's shorter and needs no invented name, but it
  repoints every other actor on `ollama`. That includes actors already moved, and the audition's, which use the
  local default. And two old actors on different hosts would overwrite each other. A side review caught this in an
  earlier draft of this design. A runtime named after the actor is a name the person can rename later, and it
  changes nothing they didn't ask to change.

### D6. The audition writes the runtime and the model

`_ollama()` returns `runner: ollama`, `runtime: ollama`, `model: OLLAMA_AUDITION_MODEL`, and no `options` key. The CLI
note in `init.py` reads the model with `_value(entries, actor, "model")`, not `_option`. `test_cli_init`'s Ollama
journey points the run at its stand-in with `TROUPE_RUNTIME_OLLAMA_ENDPOINT` in the session's environment, not
`config set …options.endpoint`. That also exercises the env override end to end.

### D7. Tests, fixtures and the capture tool follow the runtime

- The harness and the fake endpoint's tests send `run/start` with a `runtime` (`name` `test`, the fake's URL, a model,
  `credential` false) and options without `model` or `endpoint`.
- `test_runner_conformance` gives the Ollama runner a `RunStartRuntime`. The suite already passes one to a runner that
  requires a runtime.
- `capture_ollama.py` builds the runtime from `--endpoint` and the scenario's model. The scenario's `options` drop
  `model`, and the scenario gets a `model` field.
- The fixtures' `provenance.options` drop `model`. `provenance.model` stays and becomes the runtime's model in the
  replay. Only provenance is edited. The recorded exchange and events stay byte for byte, since the request body
  Ollama saw is unchanged, and the fixture replay test is what proves that.
- Core tests that ran Ollama through `options.endpoint` (`test_perform_ollama`, `test_ollama_host`) set the actor's
  runtime and point it at the stand-in through `runtimes.ollama.endpoint` or `TROUPE_RUNTIME_OLLAMA_ENDPOINT`.

## Risks / Trade-offs

- **[A theatre with an old Ollama actor can't record any config change until it's moved]** → The refusal's fix is the
  move, in one command, so the dead end lasts one copy-paste. The runner is unreleased (0.2.0 milestone), so only
  people on a development install have such actors.
- **[An old actor on a non-default endpoint gets a runtime named after it, which the person didn't choose]** → The
  fix shows the name before anything is recorded. The person can run it with another name, or rename the runtime
  later. Any name works as long as config stays valid.
- **[An Ollama runtime with a credential is refused at the runner, after the run's start is recorded]** → The run ends
  `could-not-start` with `ollama.credential-unsupported`, which names the runtime. D3 says how a follow-up can move it
  earlier.
- **[The runner works out the env variable's name itself]** → If core's rule changed, the fix text would drift. A test
  pins the runner's rule to core's for the built-in names and a hyphenated one.

## Migration Plan

For a person on a development install: the next `config set` or `perform` names the command. Run it, then commit
`.troupe/`. Nothing else changes. Runs, events and the artifact store are untouched, and old runs' starts keep the
options they recorded. To roll back, revert the commit. The old runner accepts the old options, and the new actor's
`runtime` and `model` would then be refused by the old table (`takes no runtime`), so the person would revert their
config commit too.
