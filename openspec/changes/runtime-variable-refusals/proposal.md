# Proposal

## Why

The split review of #297 found two gaps in how core handles runtime variables (#298). `runtime.invalid-value` quotes
the refused value in its problem and its details, so a person who puts their key in
`TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV` by mistake has the key printed and recorded. And a credential read with a line
ending (a `.env` file saved with CRLF, say) reaches the runner whole: the OpenAI runner refuses it, but every runner
given a credential would have to repeat that check.

## What Changes

- `runtime.invalid-value` names the variable and what its field accepts, never the value, for every runtime variable
  (`_ENDPOINT`, `_MODEL` and `_CREDENTIAL_ENV`). Its details drop `value`. The code first appeared after protocol
  0.1.0, so no released protocol carries the field and nothing outside this repository reads it.
- A new refusal, `runtime.credential-malformed`: when a run starts, core refuses a credential whose value holds
  whitespace or a control character, naming the runtime and the variable, never the value, before anything is recorded
  and before any runner is started.
- When a credential's variable name came from `TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV`, `runtime.credential-unset`,
  `runtime.credential-malformed` and `runtime.credential-too-short` name that `TROUPE_RUNTIME_` variable, never the
  name it holds. A key with only letters, digits and `_` passes the variable pattern, so troupe would otherwise repeat
  it as a name. Their details carry `variable` or `namedBy`, never both. A name from config or a built-in is still
  shown. `config get --resolved` still shows it, which #306 tracks.
- What a credential may hold is defined once, in the plugin SDK's credential module, and used by both core and the
  OpenAI runner. The runner's own check (`openai.malformed-credential`) stays: a runner can't assume its host checked.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runtimes`: a malformed runtime variable's refusal no longer names the value; a run's credential holding whitespace
  or a control character is refused with `runtime.credential-malformed`; a credential refusal never repeats a variable's
  name taken from the environment.

## Impact

- `packages/troupe/src/troupe/core/runtimes.py` (`_from_env`, `for_run`) and `core/errors.py` (the new code's exit
  code).
- `protocol/schemas/error.schema.json` and the troupe package's copy: `runtime.invalid-value`'s details lose `value`;
  `runtime.credential-malformed` is catalogued; it, `runtime.credential-unset` and `runtime.credential-too-short` take
  `runtime` and exactly one of `variable` and `namedBy`. A protocol `feat`/`fix`, not breaking (no
  released protocol has the field).
- `packages/troupe-plugin-sdk/src/troupe_plugin_sdk/credential.py`: one predicate for a well-formed credential. The
  OpenAI runner (`plugins/runner-openai/src/troupe_runner_openai/runtime.py`) uses it, with unchanged behaviour.
- Tests: `test_runtimes.py`, `test_perform_runtime.py`, the SDK's and the OpenAI runner's tests.
- Docs: `contributing/config.md`'s runtime error table, and the OpenAI runner's README, which says core refuses first.
- Specs: no Purpose changes, so no `oob/troupe-spec-purposes.json` update in infrastructure.
