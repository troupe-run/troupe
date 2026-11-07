# Design

## Context

`troupe.core.runtimes` resolves a runtime from troupe's built-ins, the theatre's config and the session's environment
(runtimes design D2, D3). `_from_env` checks each `TROUPE_RUNTIME_<NAME>_<FIELD>` against its field's pattern and
refuses a mismatch with `runtime.invalid-value`, putting the raw value in `problem` (as `repr`) and in
`details.value`. `for_run` reads the credential's value when a run starts and refuses it when unset
(`runtime.credential-unset`), shorter than `CREDENTIAL_MIN_BYTES` (`runtime.credential-too-short`), or bound for a
plain-HTTP non-loopback endpoint (`runtime.insecure-endpoint`). It doesn't look at what the value holds. perform calls
`for_run` before it records anything or launches the runner (`core/runs/perform.py`), and rehearsal goes through the
same call.

The OpenAI runner (#297) refuses a credential holding whitespace or a control character with
`openai.malformed-credential`, using `c.isspace() or not c.isprintable()` inline in
`troupe_runner_openai/runtime.py`. Both core and the runner already import from `troupe_plugin_sdk`. Core imports its
endpoint and model patterns from `troupe_plugin_sdk.runner`, and the runner gets its credential from
`troupe_plugin_sdk.credential`.

`runtime.invalid-value` and the other `runtime.*` codes came in after protocol 0.1.0 (`git show
protocol-v0.1.0:protocol/schemas/error.schema.json` has none of them).

## Goals / Non-Goals

**Goals:**
- No `runtime.invalid-value` holds the refused value, in any field, for any of the three variables.
- One definition of "a credential's value is well formed", used by core and by the OpenAI runner.

**Non-Goals:**
- `config get --resolved` still shows a credential variable's name taken from the environment, which can be a key
  that matches the variable pattern. That command exists to show what the person set, so hiding it is a separate
  decision, tracked in #306.
- `config get --resolved`'s `set` flag stays "the variable is non-empty". It doesn't judge the value: that happens
  when a run starts, as it does today for a too-short key.
- Other runners. Ollama and the scripted runner take no credential. A runner that does keeps its own check (the
  issue's out-of-scope item).

## Decisions

### D1: Drop the value from every runtime variable's refusal, not only the credential's

The issue asks for "a credential's variable at least". The refusal will leave the value out for all three fields.
- An endpoint is refused for carrying user info, the exact case where echoing it prints a password
  (`https://user:secret@host`).
- A person can paste a key into `_MODEL` as easily as into `_CREDENTIAL_ENV`.
- One shape for one code is simpler for each surface to render than details whose keys depend on the field.

The problem says the variable is set to something that isn't what the field accepts. The fix and
`details.accepted` say what is accepted, and `details.variable` names the variable. The person can read their own
value from their environment. Leaving the value out loses nothing they don't already have.

*Alternatives:* keep the value for `_ENDPOINT` and `_MODEL` (rejected: the user-info case leaks, and the shape would
vary by field). Show a masked or truncated value (rejected: any part of a key is a leak, and a short value would
show almost whole, the reason `CREDENTIAL_MIN_BYTES` exists).

### D2: Remove `value` from `runtime.invalid-value`'s details without a breaking-change marker

The details schema is closed (`additionalProperties: false`), so `value` comes out of both `required` and
`properties` in `protocol/schemas/error.schema.json` and in the troupe package's copy. No released protocol has the
code, so this isn't a breaking change to anything published, and the commit is a plain `fix(runtimes)`. The protocol
changelog picks it up from the commit at the next release.

### D3: A new code, `runtime.credential-malformed`, with details `runtime` and `variable`

It follows `runtime.credential-unset` and `runtime.credential-too-short` in name and shape. Its exit code is
`FAILURE`, like theirs (`core/errors.py`). The problem says the credential in `<variable>`, for the runtime `<name>`,
holds whitespace or a control character, such as a line ending left from the file it was read from. The fix says to
set the variable to the key alone. Neither holds the value.

*Alternative:* reuse `runtime.invalid-value` (rejected: that code is about a `TROUPE_RUNTIME_` variable's shape, and
its details name what's accepted for a field, while this is about the credential's value in a variable the person
named).

### D4: The check runs after "unset" and before "too short"

The order in `for_run` becomes unset, then malformed, then too short, then insecure endpoint. A value like `"abc\n"`
is both malformed and too short. Telling the person about the line ending first points at the likelier cause, a key
read from a file. The insecure-endpoint check stays last, as it doesn't depend on the value.

### D5: The rule lives in the plugin SDK's credential module

`troupe_plugin_sdk.credential` gets one predicate, `well_formed(value: str) -> bool`: true when no character is
whitespace (`str.isspace`) or unprintable (`not str.isprintable`, which covers C0 and C1 controls, separators and
other non-printing characters). Core's `for_run` and the OpenAI runner's `Runtime` both call it. That keeps one
definition, in the module that already describes a run's credential, which both sides already import. The SDK
depends only on the standard library, and this adds no dependency.

The runner keeps its own refusal and code (`openai.malformed-credential`): only the predicate is shared. Its
behaviour doesn't change, which the runner's existing tests confirm.

*Alternatives:* define it in core and leave the runner's inline copy (rejected: two definitions of one rule, which
would drift). Put it in `troupe.core.defaults` (rejected: plugins can't import core, per the plugin-sdk spec).

### D6: A credential refusal never repeats a variable's name taken from the environment

A key made only of letters, digits and `_` (a hex key, say) put in `TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV` passes the
variable pattern, so D1 doesn't catch it, and troupe would repeat it as the variable's name. So when the credential's
`Sourced` name has source `env`, `runtime.credential-unset`, `runtime.credential-malformed` and
`runtime.credential-too-short` name the `TROUPE_RUNTIME_` variable that held it, in the problem, the fix and the
details, and leave the name out. A name from the theatre's config or a built-in is shown as it is: config is already
committed, and a built-in is troupe's own.

The details carry either `variable` (the name, from config or a built-in) or `namedBy` (the `TROUPE_RUNTIME_` variable
that held the name), never both. Each of the three codes' details schemas requires `runtime` and exactly one of the
two (`oneOf`), still closed. No released protocol has these codes (D2), so nothing published breaks. One helper in
`troupe.core.runtimes` builds this part of the problem, fix and details for all three, so they can't disagree.

This isn't a guess: troupe doesn't judge whether a name looks like a key. It never repeats a name it took from the
environment, where the person can read it.

*Alternatives:* put the `TROUPE_RUNTIME_` name in `variable` (rejected: one key with two meanings misleads a surface
that reads it). Hide only names that look like keys (rejected: a guess). Cover only `credential-unset`, the one a
key-as-name would actually hit (rejected by the owner, 2026-11-07: one rule for all three, so they can't disagree).

## Risks / Trade-offs

- [A key that matches the variable-name pattern, put in `_CREDENTIAL_ENV`, is still shown by `config get
  --resolved`] → A non-goal here, tracked in #306. D6 keeps it out of every refusal.
- [The runner now needs an SDK with `well_formed`] → The bundle pins the SDK alongside the runner (runner-sdk D12), so
  they release together. The SDK change is a `feat(plugin-sdk)`, so release-please releases a new SDK version, which the
  runner picks up through the bundle's pin.
- [`isprintable` rejects some non-ASCII characters a key could in theory hold] → API keys are ASCII. A header value
  can't carry them unencoded anyway, and the OpenAI runner already applies this rule, so core is no stricter than the
  runner a person would hit next.
