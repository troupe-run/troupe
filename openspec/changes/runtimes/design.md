# Design: runtimes

## Context

See proposal.md for why. What this builds on:

- **Config** (`troupe.core.config`): one event stream per theatre, checked whole by `config/kinds.py` before a change
  is recorded and when branches merge, projected to `.troupe/` by kind. It has one kind, `actors`.
- **Settings and policy** (`troupe.core.settings`, `troupe.core.policy`): each value is read through one seam, from
  `defaults.py` and then the session's environment, and carries its source (`default` or `env`). Unset or empty is
  absent; anything else that isn't valid is an error. This change follows the same shape for runtimes, with a third
  source, the theatre's config.
- **The runner table** (`troupe.core.interim.RUNNERS`): the only place a runner's name becomes a command line, and
  the variables perform copies into the runner's environment. Nothing else reaches the runner.
- **The run host** (`troupe.core.runners.host`): reads the runner's run events, transcript records (base64 ones
  decoded) and standard error, and stores them; it's the one place everything a runner sends passes through.
- **The runner contract, version 0** (`protocol/schemas/runner/`), and the plugin SDK's types for it.
- **#162's design (D2)** assumed this hand-off: `run/start` carries a `runtime` with the endpoint and model and
  whether there's a credential, and the value arrives in the runner's environment under one variable the contract
  names. This design keeps that shape.
- **#277** (Ollama, PR #283) takes its endpoint and model in its options today.

## Goals / Non-Goals

**Goals:**
- One place to define a service, used by every runner that talks to one.
- A credential that is only ever a variable's name in anything committed or recorded.
- Every resolved value can be traced to where it came from: in `config get --resolved`, a rehearsal and the run's
  start.
- The credential's value can't reach anything troupe writes, even from a runner that leaks it.

**Non-Goals:**
- Deciding which endpoints may receive a credential, or which variables config may name. That's policy, later (D7).
- Any runner's own use of a runtime (#277, #162): what it sends, how it authenticates, its retries.
- Masking what a run writes into its workspace. That's the run's output; `troupe diff` shows it before it's accepted.

## Decisions

### D1. A runtime holds an endpoint, a model and a credential reference

`protocol/schemas/config/runtime.schema.json`, closed, with its field types in a shared `protocol/schemas/runtime.schema.json`
(as `effects.schema.json` is shared), which `run/start`, the run's start and the client also use:

| Field | Type | Notes |
|---|---|---|
| `endpoint` | URL | `http` or `https`, a host, no user info, query or fragment. A path is allowed (`/v1`). |
| `model` | string | Non-empty. The default for actors on this runtime. |
| `credential.env` | string | `^[A-Za-z_][A-Za-z0-9_]*$`, not starting with `TROUPE_` (case-insensitively, for Windows). |

Every field is optional in the schema, because a runtime in config may only override a built-in (D2). `kinds.py`
requires `endpoint` for a runtime that isn't built in. The endpoint is the base URL the runner's API lives under:
`http://127.0.0.1:11434` for Ollama's own API, `https://api.openai.com/v1` for Chat Completions. The runner appends its
own paths.

`credential` is a group, so it can grow (a later secret store, #278's parked work) without changing what `env` means.
Refusing `TROUPE_` names keeps config from pointing a credential at troupe's own variables, the hand-off variable
among them.

**Alternatives:** a `credential` that is a string (the variable's name) is shorter, but leaves no room for another
kind of reference. An `api` field naming what the endpoint speaks would catch an actor on the Ollama runner pointed at
a Chat Completions URL, but nothing yet needs it, and the runner's first request fails clearly anyway (Risks).

### D2. Built-in runtimes are defaults in one place

`troupe.core.defaults.RUNTIMES` holds `openai` (`https://api.openai.com/v1`, `credential.env: OPENAI_API_KEY`),
`ollama` (`http://127.0.0.1:11434`) and `lm-studio` (`http://127.0.0.1:1234/v1`). These are the services 0.2.0's
runners target (#277; #162 and its LM Studio follow-up on #56). None names a model: models are renamed and retired,
and a default would go stale in a release nobody updates. A run with no model is refused, naming the three places one
can be set.

A built-in isn't config: it isn't an event, has no file, and `config get` (without `--resolved`) doesn't show it. A
theatre that sets `runtimes.openai.model` overrides that one field; the endpoint and credential stay the built-in's.
A theatre can't remove a built-in's credential; it defines a runtime of its own instead.

### D3. Resolution: defaults, then the theatre, then the environment

One module, `troupe.core.runtimes`, resolves a runtime into a `Resolved` value object: each field's value and source
(`default`, `theatre` or `env`; the model can also be `actor`). Each field is resolved on its own: the highest source
that sets it wins.

- **Variables:** `TROUPE_RUNTIME_<NAME>_ENDPOINT`, `_MODEL` and `_CREDENTIAL_ENV`, `<NAME>` the runtime's name in
  capitals with `-` as `_`. Names can't hold `_`, so two runtimes never map to the same variable. Only the variables of
  runtimes that exist are read, as settings read only the settings that exist: a `TROUPE_RUNTIME_` variable for a
  runtime this theatre doesn't have is someone else's, perhaps another theatre's, and isn't an error.
- **The model** is the environment's, then the actor's, then the runtime's in config, then none. The person's
  environment is the top of the chain everywhere else, so it stays the top here: `TROUPE_RUNTIME_OPENAI_MODEL` points
  every actor on `openai` at one model, which is what a person testing against a cheaper or local model wants.
- **Validation** of a variable's value uses the same checks as the schema (D1), so config and the environment accept
  the same things; a property test checks they agree. A bad value is `runtime.invalid-value` (D10).
- **When:** resolution reads the environment, so it happens per command, in perform, a rehearsal and
  `config get --resolved`, never when config is checked. Config's check covers only what config holds (D4).

**Alternative:** resolving an actor's model above the environment, so a committed choice always wins. Rejected: the
person running troupe would have no way to point a run elsewhere without changing committed config.

### D4. Actors name a runtime; the runner table says who takes one

The actor schema gains `runtime` (the actor-name pattern) and `model`. `interim.Runner` gains
`runtime: Literal["required", "optional", "none"]`: `claude-code` is `none`, `scripted` is `optional` (for tests),
and #277 and #162 add theirs as `required`.

`kinds.py` checks, across the kinds: an actor's runtime is built in or in config; a runner that takes none has no
runtime; a runner that requires one has one; `model` needs a runtime. Because config is checked whole, unsetting a
runtime an actor uses is refused, and a merge that does it is a conflict, with no new mechanism.

### D5. The hand-off: the runtime in `run/start`, the value in the environment

`run/start`'s params gain an optional, closed `runtime`: `name`, `endpoint`, `model` (all required) and `credential`
(boolean, required). The SDK's `RunStartParams` gains the same. The value goes in the runner's environment as
`TROUPE_RUNTIME_CREDENTIAL`, added by perform after the runner table's variables, so a `TROUPE_RUNTIME_CREDENTIAL`
already in perform's own environment never passes through. The variable config names (`MY_OPENAI_KEY`) isn't passed:
the runner needs only the value, and naming one variable in the contract keeps every runner the same.

The credential is read with the platform seam's name matching, so `credential.env` is case-insensitive on Windows, as
the runner table's names already are.

**Alternatives:**
- **The value in `run/start`:** `run/start` is what troupe records of a run's input (#278), so the value would be
  written. Rejected by #278.
- **A separate JSON-RPC message** (`run/credential`) troupe never records: it keeps the value out of the process's
  environment, but adds a method every runner must handle and a message the host must take care never to log. A
  runner's environment already holds the person's own keys today (the Claude Code runner's), and #162's runner was
  designed for the environment. Kept for later if a stage needs it.

The contract version stays 0 (the draft); the protocol gets a minor release, since the field is optional and no
existing runner receives it (the scripted runner is the only one that takes a runtime, and it ships with this).

### D6. troupe masks the credential in what it keeps

The runner contract says a runner never sends the credential back. troupe doesn't rely on it: the run's `Masker`, made
in perform when the credential is read, is applied where the host takes in what a runner sends, before anything is
stored or forwarded:

- **Run events:** every string in the parsed event, recursively, before it's checked against `eventMaxBytes` and
  recorded.
- **Transcript records:** the record's bytes (after base64 decoding, which the host already does), before they're
  written.
- **Standard error:** a streaming mask that holds back the last `len(value) - 1` bytes of each chunk until the next
  chunk or the end, so a value split across reads is still caught.
- **Errors and notices:** a runner's error response, and any error perform raises during the run, pass through the
  same mask before they're recorded or sent.

Each mask replaces the value's UTF-8 bytes and its JSON-escaped forms (as `json.dumps` writes it, and with `/` as
`\/`) with `[credential]`. The marker is fixed, so a reader can tell a masked value from text.

**The minimum length** (`defaults.CREDENTIAL_MIN_BYTES`, 8) exists for masking: a short value such as a placeholder
`ollama` would match ordinary text, corrupting records, while a real key is far longer. A runtime that needs no key
has no credential, so a placeholder is never needed.

**Alternative:** masking only in each runner (#162 D11 does too). Kept as well, but a runner is a plugin, and the
guarantee "nowhere troupe writes" has to hold for the code troupe runs, not the code it trusts.

### D7. Accepted risks: config chooses the endpoint and the variable

Config is committed. A theatre's config, including one merged from someone else's branch, can:

1. set a runtime's `endpoint`, so the person's credential goes to that host (#160's finding), and
2. set `credential.env`, so a different variable of the person's (say `AWS_SECRET_ACCESS_KEY`) is sent, to an
   endpoint they did approve.

**Both are accepted for now (owner, 2026-11-04, on #278).** Policy will limit both the endpoints a credential may go
to and the variables config may name ("policies enforce allowed structures later on to limit both URLs and acceptable
keys"). This change files that as a follow-up issue. Until then they're visible rather than prevented: the run's start
records the endpoint and variable with their sources (D8), and a rehearsal and `config get --resolved` show them
before a run.

What troupe still refuses, since it isn't about who chose the endpoint: a credential over plain HTTP to anything but a
literal loopback host (`localhost`, `127.0.0.0/8`, `::1`; no DNS lookup, which could be made to lie), and a
credential too short to mask (D6). Runners add their own defences (#162 refuses redirects).

**Alternatives** (asked, 2026-11-04): refusing a credential to an endpoint only theatre config set until the person
sets `TROUPE_RUNTIME_<NAME>_ENDPOINT` themselves, or a separate trusted-endpoint variable. Both deferred to policy.

### D8. The run's start records the runtime

`Run.Started`'s payload gains an optional `runtime`: `name`, `endpoint` `{value, source}`, `model` `{value, source}`
and, with a credential, `credential` `{env: {value, source}}`. Earlier runs have none. The record is what a person
reviewing a run needs to see where it talked to and with which key, without the key. It's in the event, not a
lineage field, as the stage is.

### D9. `config get --resolved`, and `troupe runtimes` later

`config-get-request` gains `resolved` (boolean). With it, the result gains `runtimes`: for each runtime (built in or in
config, or the one a path names), each field's value and source, and for a credential `{env: {value, source},
set: bool}`. The value field is unchanged. A path that isn't `runtimes` or `runtimes.<name>` is refused with
`config.not-resolvable`, naming the path. The core query holds the
behaviour; the CLI only renders it.

`troupe config get` is the surface for now (owner, 2026-11-04). A `troupe runtimes` command is noted for later: once
troupe can store a secret (`troupe runtime auth`, say), runtimes will have more than config to show.

### D10. Errors

Added to the error catalogue, each with closed details and never the credential's value:

| Code | Details |
|---|---|
| `runtime.invalid-value` | `variable`, `value`, `accepted` |
| `runtime.no-model` | `runtime`, `actor`, `places` (the config paths and variable that can set it) |
| `runtime.credential-unset` | `runtime`, `variable` |
| `runtime.credential-too-short` | `runtime`, `variable`, `minimumBytes` |
| `runtime.insecure-endpoint` | `runtime`, `endpoint` |
| `config.not-resolvable` | `path` |

Config's own refusals (an unknown runtime, a runner that takes none) are config problems with paths, as today.

### D11. The scripted runner's runtime steps

- `checkRuntime`: `{"name", "endpoint", "model", "credentialHash"}` (each optional; `credentialHash` a `sha256:` of
  the value's UTF-8, or `"noCredential": true` for none, since the schemas carry no nulls), or `{"absent": true}`. A mismatch is an error result naming each field, with
  hashes in place of the credential, like `checkCharacter`.
- `echoCredential`: `true`. Sends the value in a `log` event, a transcript record and standard error. It exists only to
  test troupe's masking; its README row says so.

### D12. The leak test

`packages/troupe/tests/test_credential_leak.py` sets a canary (a random 40-character key with a `/`, so the JSON-escaped
form differs), defines a runtime on it, and drives troupe's command line through: a successful run whose runner echoes
it in a log event, a transcript record and standard error; a failed run that does the same; a refused run
(`runtime.insecure-endpoint`); a rehearsal; `config get` with and without `--resolved`; and `status` and `logs`. The
scripts never hold the key, since config holds them: only the runtime brings it in. A key split across two reads of
standard error, base64 records and the JSON-escaped forms are tested in perform's and the masker's own tests. It then
reads every file under `.troupe/` and the artifact store, and every client message the session sent, and fails naming
the place if any holds the canary, its JSON-escaped form or its base64 form. A second test checks the test would catch a
leak: with masking turned off through the test's seam, it fails.

## Risks / Trade-offs

- **A theatre's config sends the person's credential to its own endpoint, or sends another of their variables**
  → accepted for now, recorded with sources in every run's start, shown before a run; policy limits it later (D7).
- **A runner writes the key into the workspace** → not masked: it's the run's output. `troupe diff` shows it before
  `accept`, and the contract forbids it.
- **Masking misses a form troupe doesn't know** (a runner that base64-encodes text inside a record, say) → the exact
  value and its JSON forms are masked; the runner contract forbids sending it at all; the leak test scans for the
  base64 form too.
- **The environment overrides an actor's committed model** → by design (D3); the run's start records `env` as the
  source, so it's visible afterwards.
- **An actor on one runner pointed at a runtime for another API** → the runner's first request fails with the
  service's error; an `api` field can be added when that's common (D1).
- **#277 or #162 merges first with a different shape** → #162 already assumes D5's shape. #277 takes its endpoint
  and model in options; moving it to a runtime is a follow-up of its own, filed by this change if #277 merges first.

## Migration Plan

Nothing existing changes behaviour: no actor names a runtime today, and `run/start` and `Run.Started` gain only
optional fields. The protocol releases a minor version. Rolling back removes the kind; a theatre that has runtimes in
config would then refuse its config, naming `runtimes`, which is the safe outcome.
