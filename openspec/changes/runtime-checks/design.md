# Design: runtime, credential and actor-file checks

## Context

See proposal.md for why. The code this touches, as it is on main (`3678f411`):

- **Runner table.** `troupe.core.interim.RUNNERS` maps a runner's name to a frozen `Runner`: `command`, `package`,
  `environment`, and `runtime` (`"required"`, `"optional"` or `"none"`). PR #338 (#333, not yet merged) adds
  `in_extra: bool = False` after `runtime`, a docstring citing its design, and `installed_runner()`. The table is
  interim: when plugins are named in config (#38) it is deleted, and what it says moves to each plugin's declaration.
- **Actor rules.** `core/config/kinds.py`: `problems(config)` checks runtimes, then each actor with
  `actor_problems(name, actor, runtime_names(config))`. `_runtime_problems` knows only runtime *names*, so it can say
  whether a runtime exists and whether the runner takes one, not whether it fits. A `Problem`'s `related` paths make a
  merge's change to a runtime count as a change to the actor's rule.
- **Resolution.** `core/runtimes.py`: `resolve(name, config, env)` gives each field with its source (`default`,
  `theatre`, `env`); `for_run` adds the model and the credential's value, refusing with `runtime.no-model`,
  `runtime.credential-unset`, `-malformed`, `-too-short` and `runtime.insecure-endpoint`. `_from_env` already refuses
  a malformed variable without its value (#298, `610096d9`), which closed the environment half of #323.
  `Resolved.to_data(env)` feeds only `config get --resolved`; `RunRuntime.to_data()` feeds the run-started event,
  perform's result and a rehearsal.
- **The runners' own rules.** The Ollama runner (`troupe_runner_ollama/runtime.py`) refuses a runtime with a credential
  (`ollama.credential-unsupported`) and an endpoint with a path (`ollama.invalid-runtime`), treating a lone trailing
  `/` as no path. The OpenAI runner refuses an endpoint that isn't a base http(s) URL (`openai.no-runtime`), and
  appends `/responses` to any other. The scripted runner takes any runtime.
- **The SDK.** `troupe_plugin_sdk.credential.well_formed` refuses whitespace and unprintable characters only.
  `messages._decode` refuses a pattern mismatch with `f"{value!r} doesn't match {pattern}"`, so `RunStartRuntime`'s
  `endpoint` field quotes a refused endpoint, password included.
- **Projection.** `core/config/projection.py`: `FIELD_ORDER = ("$schema", "runner", "options", "expect")`, while the
  actor schema's properties are `$schema, runner, options, expect, effects, workspace, runtime, model`.
  `RUNTIME_FIELD_ORDER` is already held to its schema by a test (`test_config_files.py`).

## Goals / Non-Goals

**Goals:**
- One rule for runtime fit, in one named place, applied by config (to config's values) and by perform (to the
  resolved values), and agreeing with what each runner itself refuses.
- One definition of a sendable credential, used by core and every runner.
- No surface repeats an endpoint's user info or a credential variable's name taken from the environment.

**Non-Goals:**
- Checking that a service is what its endpoint claims (the runners' preflights), or which hosts are allowed (#286).
- Changing what the run-started record holds for a credential (D6).
- Masking endpoints in what troupe records: an endpoint with user info is refused before anything is recorded, so
  there's nothing to mask.

## Decisions

### D1. A runner's runtime fit is a field of the runner table

`Runner` gains `fit: RuntimeFit`, after #338's `in_extra`, in the same style (a typed field with a docstring citing
this design):

```python
@dataclass(frozen=True)
class RuntimeFit:
    credential: bool = True      # whether the runner sends a runtime's credential
    path: Literal["any", "none", "required"] = "any"   # what the endpoint's path must be
```

Table: `ollama` → `RuntimeFit(credential=False, path="none")`; `openai` → `RuntimeFit(path="required")`; `scripted`
and `claude-code` take the default (scripted takes any runtime; claude-code takes none, which `runtime="none"` already
refuses). An endpoint "has a path" when its path, with leading and trailing `/` removed, isn't empty: the Ollama
runner's own reading.

*Alternatives:* a list of built-in runtimes each runner fits (rejected: says nothing about a runtime defined in
config, which #334 puts in scope); a fit declared by the plugin (the eventual home under #38, but there's no plugin
declaration to put it in yet, and the table is where #338 put `in_extra`). The fit is judged only from fields config
holds, so it works whether or not the runner is installed, which #338's D7 needs for an actor on an uninstalled
runner.

### D2. One judging function, in `core/runtimes.py`

`runtimes.unfit(fit, endpoint, has_credential) -> list[Reason]`, where a reason is `"credential"`, `"endpoint-path"`
(has a path, needs none) or `"endpoint-no-path"`. Config and perform both call it; nothing else judges fit.

### D3. Config judges a runtime from its built-in and theatre values

`problems(config)` passes `actor_problems` a mapping of each runtime's name to its fields as `resolve(name, config,
{})` gives them: the built-in values overridden by the theatre's, no environment. Config is committed and shared, so
its check can't depend on one person's environment. A runtime that has problems of its own (no endpoint, a schema
error) isn't judged for fit; its own problem is reported. The fit problem's `related` holds the runtime's path, so a
change to `runtimes.ollama.credential.env` with an `ollama` actor on it is refused, naming the actor, through the
existing mechanism. `actor_problems`'s `runtimes` argument changes from a list of names to that mapping; its other
caller on main (`kinds.py`'s single-actor refusal, used by perform) passes the same. #338 adds a keyword-only
`touched` to `actor_problems`, `problems` and `check`. For an actor on a known runner that isn't installed and that
the change doesn't touch, it skips only the options, so fit is still judged there.
`config/stream.py` calls `check`, not `actor_problems`, so it needs no change.

The "needs a runtime" and "no such runtime" problems list only the runtimes that fit the actor's runner. When none
fits, the rule says so and the fix is `troupe config set runtimes.<name>.endpoint=<url>`, with the path rule in words.

### D4. Perform judges the resolved runtime, and refuses with `runtime.unfit`

`for_run` takes the actor's runner and judges fit right after `resolve`, before the model and the credential, so the
credential's variable is never read for a runtime that can't take it, and the root cause is reported rather than a
`runtime.credential-unset` it would lead to. This covers what the environment can change after config accepted the
pair: `TROUPE_RUNTIME_<NAME>_ENDPOINT` and `_CREDENTIAL_ENV`. A rehearsal goes through `for_run` too.

`runtime.unfit` is a new code in the error catalogue (`error.schema.json`, both copies) with details `actor`,
`runner`, `runtime`, `reasons` (the D2 values), `from` (for each reason, where its value came from: the
`TROUPE_RUNTIME_` variable, the config path, or `default`) and `fits` (the runtimes that fit, judged the same way,
leaving out any whose variables are malformed). It holds no endpoint and no credential variable's name, so the
"never repeat a name from the environment" rule (#298 D6) holds by construction. Its fix names where to change each
value. Per the protocol guard, the code lands with the code that raises it and a test that raises it.

### D5. The OpenAI runner refuses an endpoint with no path

`Runtime.checked` refuses it with `openai.no-runtime`, `where: runtime.endpoint`, as it refuses other unusable
endpoints, saying the endpoint needs a path such as `/v1`. This keeps config and runner agreeing, which a
differential test holds (D9). Every OpenAI-style service known to the project (OpenAI, Ollama's `/v1`, LM Studio,
vLLM, llama.cpp's server, OpenRouter's `/api/v1`) serves under a path; one that also serves at its root (a LiteLLM
proxy) serves under `/v1` too. Owner's choice, 2026-11-11.

### D6. A credential variable's name from the environment shows as `namedBy`

`Resolved.to_data(env)` gives `credential.env` as `{"namedBy": "TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV", "source":
"env"}` when the name came from the environment, and `{"value", "source"}` otherwise; `set` is computed as now.
`runtime.schema.json#/$defs/resolved`'s `credential.env` becomes a `oneOf` of the two forms, and the client message
type and `cli/runtimes.py` follow ("credential: from the variable TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV names, not
set"). This is #298 D6 applied to the one surface it missed.

`RunRuntime.to_data()` (the run-started event, perform's result, a rehearsal) keeps the name. A run or rehearsal gets
there only after `for_run` found that name set to a well-formed key of at least the minimum length, so it names a
variable, and lineage keeps which. Owner's choice, 2026-11-11 (option "name the setter", not "run record too").

*Alternative:* keep showing the name, since the command exists to show what the person set (rejected by the owner).

### D7. A sendable credential is visible ASCII

`well_formed(value)` becomes "every character is between `!` and `~`". That subsumes today's rule (whitespace and
control characters are outside the range) and adds everything non-ASCII. RFC 9110 field values are visible ASCII
plus obsolete text, and httpx, which the library-backed runners (#331, #332) will use, encodes header values as
ASCII, so Latin-1 would pass here and fail there. Core's `runtime.credential-malformed` and the OpenAI runner's
`openai.malformed-credential` keep their codes; their words change to "a character a request header can't carry, such
as a space, a line ending or a letter outside ASCII". Owner's choice, 2026-11-11.

The minimum length is measured in UTF-8 bytes today; for a well-formed credential bytes and characters are now the
same, so nothing changes there.

### D8. The SDK never quotes a refused endpoint

`json_field` gains `unquoted: str | None`, the words for what the value must be; `RunStartRuntime.endpoint` sets it
to `ENDPOINT_ACCEPTED`. A pattern mismatch on such a field raises `"<field>: isn't an endpoint: an http or https URL
with a host, and no user info, query, fragment, whitespace or control character (its value isn't shown)"`, naming the
field and no part of the value. (Changed while building: the plan had `quoted: bool`, but the refusal needs the
words, so the one field carries both.) Other pattern-checked fields (run ids, refs, model
names) keep quoting, since their values are troupe's own and quoting them helps.

*Alternative:* strip user info from the quoted value. Rejected: a value that fails the pattern isn't a well-formed
URL, so where its user info ends is a guess.

The other places an endpoint is quoted on refusal, checked for #323:

| Where | Can it hold user info? | Change |
|---|---|---|
| `config set` (runtime schema, `config.invalid`) | refused by the pattern | none; a canary test |
| `TROUPE_RUNTIME_<NAME>_ENDPOINT` (`runtime.invalid-value`) | refused, value not quoted since #298 | a CLI test on standard error and the client message |
| SDK `run/start` (`runner.invalid-params`) | yes, today | D8 |
| `runtime.insecure-endpoint` (core) | no: the endpoint passed the pattern | none |
| Ollama runner `ollama.invalid-runtime` | no: the SDK refuses first | none; the D8 test shows the SDK refuses first |
| OpenAI runner `parse_endpoint` | no, after the SDK, but its message quotes a user name | never quotes a value holding `@` |
| `config get --resolved` | no: every source is pattern-checked | none |

### D9. A differential test holds config's fit to each runner's own

For each runner that takes a runtime, and a set of runtimes (the built-ins, and generated endpoints with and without a
path, a trailing `/`, a port, with and without a credential), config's verdict (`unfit` is empty) must equal the
runner's (its `checked` accepts the `RunStartRuntime`). Per the project's rule on rewriting input handling, the
runner's own check is the oracle, and a disagreement fails the test. It lives where the check-paths config reaches both
core and the runner plugins (confirmed in `scripts/check-paths.toml` when writing it).

### D10. An actor's file holds every field of its schema

`FIELD_ORDER` becomes `("$schema", "runner", "options", "expect", "effects", "workspace", "runtime", "model")`, and a
test holds it to the actor schema's properties, as `RUNTIME_FIELD_ORDER` is held. A second test builds an actor with
every schema field set through the config commands and checks the written file holds each. An actor file troupe wrote
before this change still matches what troupe last wrote, so the next flush replaces it with the fuller one: no
migration step.

### D11. Built on main, rebased past #338

This change touches `interim.py` and `error.schema.json`, which #338 also changes. It is built on main and follows
#338's shape (D1); once #338 merges, the branch is rebased onto main and `fit` goes after `in_extra`. The
`track-b-26-333` session is told what this adds to the table, so neither surprises the other.

## Risks / Trade-offs

- [A runtime that worked with the OpenAI runner at its root stops working] → the error says to add the service's API
  path, such as `/v1`; every service known to the project has one. Pre-1.0, no compatibility form.
- [A credential with a Latin-1 character that a service accepted is now refused] → no known key format uses one; the
  refusal names the variable and says what's allowed.
- [Config's fit and a runner's own drift apart] → D9's differential test; when the table moves to plugin declarations
  (#38) the rule moves with it.
- [`actor_problems`'s signature change misses a caller] → mypy --strict catches a list passed for a mapping.
- [#338 merges first and the rebase conflicts in `interim.py` and `error.schema.json`] → both are additive; the
  conflict is resolved by keeping both, then the full check runs again.

## Migration Plan

None beyond D10's rewrite on the next flush. No stored record changes shape: the run-started event is unchanged,
and `config get --resolved`'s result gains a form only in output.
