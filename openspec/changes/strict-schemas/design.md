# Design

## Context

See proposal.md for why. What exists on main (a527b43):

- 21 schemas in `protocol/schemas/`: the shared `error`, `notice`, `lineage` and `event-record`, the runner contract
  (`runner/`) and the client protocol (`client/`). Lineage and the client protocol are already closed throughout. A
  scan finds the open parts listed in #70: `event-record` `state`, `error` and `notice` `details`, `options` in
  `client/perform-request` and `runner/run-start`, `native` in `runner/run-event`, `result` in
  `runner/jsonrpc#/$defs/successResponse`, and `usage`'s untyped keys.
- Python types mirror the schemas by hand and tests validate them both ways (runner-contract D11, perform-status-logs
  D3). `jsonschema` is a dev dependency only; troupe's runtime depends on `eventsourcing` alone. Three test helpers
  (`runner_schemas.py`, `client_schemas.py`, `event_schemas.py`) each build their own registry.
- 56 error codes in `troupe.core.errors.CODES` (each with its exit code) and 8 notice codes in
  `troupe.core.notices.CODES`, raised from about 60 sites, with `details` as a free dict. Detail keys mix
  snake_case (`exit_code`, `limit_bytes`) and camelCase (`maxAttempts`). Nothing reads detail keys
  programmatically; the CLI doesn't render them.
- The scripted runner sends its own error codes: seven protocol ones (`runner.parse-error`, `runner.invalid-request`,
  `runner.not-initialized`, `runner.unknown-method`, `runner.unsupported-version`, `runner.already-started`,
  `runner.invalid-params`) that no document lists, and two of its own (`scripted.invalid-script`,
  `scripted.unknown-option`).
- A run records three topics, `troupe.core.runs.aggregate:Run.Started`, `Run.Reported` and `Run.Ended` (listed in
  `aggregate.TOPICS`). A recorded payload holds the aggregate's fields in snake_case, plus the library's own:
  `originator_topic` (on the created event) and `timestamp` as `{"_type_": "datetime_iso", "_data_": "..."}`.
  `Run.Reported` holds the run event as troupe received it; `Run.Ended` holds the derived outcome, including a
  structured error.
- `native` appears in one place in practice: the fixtures' `init` events carry Claude Code's whole `system/init`
  record, which the transcript already holds verbatim.

## Goals / Non-Goals

**Goals:**
- A check that makes "strict" mechanical, and that fails the build for any schema troupe ships, now and later.
- Close every open field on main without loosening what anything accepts in practice, except where removal is the
  decision (`native`).
- A pattern for places whose shape is defined elsewhere (a runner's options and error codes) that #60 can reuse for
  config files.

**Non-Goals:**
- Validating at run time. troupe gains no runtime dependency here; whether config and options are validated at run
  time, and with what, is #60's decision, with the type generator (#7, question 1).
- Generating Python types. Detail and payload types stay dicts in Python, checked by tests.
- Renaming recorded event payload fields to camelCase. Recorded events are history; their schemas describe them as
  they are.
- Publishing schemas anywhere but the repository.

## Decisions

### D1. The strictness check walks schemas with an evaluation context

A test walks every `*.schema.json` under `protocol/schemas/` and every `plugins/*/schemas/`, from each file's root,
following `$ref` and `$dynamicRef` into other files. It carries one flag down the walk: whether an enclosing node sets
`unevaluatedProperties: false`. The flag passes into `allOf`, `oneOf`, `anyOf`, `if`, `then`, `else` and through
references, and is cleared by `properties`, `items` and `additionalProperties`, whose children are new instances.

A node fails if:
- it is `true` or `{}` where a value is accepted (`false` is allowed: it means "never");
- it constrains nothing: no `type`, `const`, `enum`, reference or composition (annotation-only nodes such as a bare
  `description` fail; a file root holding only `$defs` is a container, not a value, and is skipped);
- it can accept an object (its `type` includes `object`, or it has `properties`) and is not closed, by its own
  `additionalProperties: false` or `unevaluatedProperties: false`, or by the flag;
- its `additionalProperties` is a schema (a map) without `propertyNames`;
- its `type` includes `array` without `items` (or `prefixItems` with `items: false`).

Each failure names the file and the JSON Pointer of the node. A second test feeds the walker hand-made bad schemas,
one per rule, and requires each to be reported at the right pointer.

The detail-key rule (camelCase) is a separate test over the error and notice catalogues.

*Alternatives.* A behavioural check, generating instances with an extra key at every object position and requiring
rejection, is closer to the meaning but needs a schema-driven generator (`hypothesis-jsonschema` isn't installed and
doesn't support `$dynamicRef`). A meta-schema that forbids open objects can't express "closed by an enclosing
`unevaluatedProperties`". The walker is small, and its own tests keep it honest.

### D2. A place that varies is a `$dynamicRef` extension point with a closed default

`options` in `run/start` and `perform`'s request becomes `{"$dynamicRef": "#runnerOptions"}`. Each schema declares
the default in its own `$defs`: `{"$dynamicAnchor": "runnerOptions", "type": "object", "additionalProperties":
false}`, which accepts only `{}`. A runner's options schema fills it through a binding schema that sets
`$dynamicAnchor: runnerOptions` on a `$ref` to the runner's schema and `$ref`s the contract. A prototype with the
repository's `jsonschema` showed: the contract alone accepts `{"options": {}}` and refuses `{"options": {"script":
"x"}}`; bound to a runner schema it accepts the runner's options and refuses an unknown key.

This is standard JSON Schema 2020-12, so other languages' validators see the same meaning, and the strictness check
sees a closed default. The tests build the bindings; #60 can build the same for actor files.

The same pattern carries a runner's own error codes (D5).

*Alternatives.* An open object with a marker keyword (`x-troupe-schema`) is still open to every tool that doesn't
know the marker. Swapping a schema in the registry under the contract's own `$id` changes what that `$id` means
depending on who loads it.

### D3. A runner publishes its schemas as files in its plugin

A runner ships `schemas/options.schema.json` and `schemas/errors.schema.json`, with `$id`s under
`https://troupe.run/plugins/<plugin directory>/`. The scripted runner's event steps refer to the contract's field
definitions for each event type, with `runId` and `seq` optional because the runner fills them in unless a step
breaks the contract on purpose; a test keeps each step's fields equal to the contract's. They pass the strictness check like troupe's own. The scripted runner's
options schema covers its options (`script` or `scriptPath`, `replayDelays`) and every step and field a script can
hold, which `script.py` already enforces by hand; its errors schema lists `scripted.invalid-script` and
`scripted.unknown-option` with their details. The plugin's tests validate every script and recording it ships against
the options schema, and every error it sends against the bound error schema.

The conformance suite gains a check: a runner refuses `run/start` options holding a key outside its options schema.
It needs only "an unknown key", not the schema itself, so the suite's inputs don't change.

How troupe obtains an installed runner's schemas at run time (from the package, or offered in `initialize`) is not
decided here: nothing at run time needs them until config (#60) and plugin acquisition (#67). Files are the
smallest thing that serves editors, tests and both of those later.

### D4. Validation stays in the tests, at the moment of construction

A pytest plugin, `protocol_guard`, loaded for every test path through `addopts = ["-p", "protocol_guard"]` (it lives
in `packages/troupe/tests`, already on `pythonpath`), wraps three points for the whole session:
- `TroupeError` and `Notice` construction: their `to_data()` is validated against the error or notice schema;
- the event service's recording path in `troupe.core.events`: each event's payload is validated against its topic's
  schema.

A failure raises inside the test that produced it, naming the code or topic and the failing detail, taken from
the catalogue branch for that code rather than every branch it missed. The session-end check (Risks) counts a code
only when troupe's own source constructs it, since tests that build every code by hand would otherwise make it pass
vacuously. The event hook sits in troupe's service,
not in the text store, because the store's own tests run the `eventsourcing` library's recorder suite, which records
arbitrary topics on purpose.

One shared registry, `protocol_schemas.py`, loads every schema in `protocol/` and in plugins once; the three existing
helpers keep their public functions and delegate to it.

*Alternative.* Validating at run time would catch the same drift in production, but needs `jsonschema` (and its
compiled `rpds-py`) as a runtime dependency, and shipping the schemas as package data. That's the decision #60 makes
anyway, with the generator, so it's taken once there.

### D5. Errors and notices: one catalogue per schema, a closed `details` per code

`error.schema.json` keeps its common fields and closes with `unevaluatedProperties: false`, with a `oneOf` holding one
branch per code: `{"properties": {"code": {"const": "run.timeout"}, "details": {"$ref": "#/$defs/details/run.timeout"}}}`.
A code with no details has a branch that forbids `details` (`"details": false`). `notice.schema.json` does the same.
Detail schemas are written from the raise sites, one per code; where several codes share a shape (`*.unknown-*`:
`{name, installed}`), they share a definition.

The runner contract's protocol codes go in a new `runner/errors.schema.json`, built the same way. Its
`$defs/anyError` is `oneOf` the contract's codes and `{"$dynamicRef": "#runnerErrors"}`, whose default is `false`,
so a code the runner hasn't published doesn't validate (D2, D3). A runner error's `data` refers to it, and so does
`runner.start-failed`'s `runnerError` detail, which keeps the runner's answer.

The Python catalogues stay where they are (`CODES`, with exit codes for errors) and a test checks that they and the
schema list the same codes. Detail keys are renamed to camelCase at every raise site as each code's schema is
written: `exit_code` → `exitCode`, `limit_bytes` → `limitBytes`, `waited_seconds` → `waitedSeconds`, and so on.

### D6. Recorded events: a payload schema per topic, describing what is recorded

New files in `protocol/schemas/events/`: `run-started.schema.json`, `run-reported.schema.json` and
`run-ended.schema.json`, each closed, with `lineage` as `lineage.schema.json`, `timestamp` as the library's
transcoded datetime, and `originator_topic` on `Run.Started`. Fields keep their recorded snake_case names.
`Run.Reported`'s `event` is the contract's `hostEvent`; `Run.Ended`'s outcome reuses the error schema for its error.

`event-record.schema.json` becomes `oneOf`: the header; a troupe event, whose `state` is chosen by `topic` through
one `if`/`then` per topic and whose `topic` is one of the known topics; or an opaque event carrying `state_b64` only.
The `troupeEvent` definition goes, since every inline event is now a troupe event.

`state_b64` stays a typed base64 string. It is bytes, not JSON, and the event store keeps it because the library's
recorder contract stores arbitrary bytes (event-store design: payload inline when exact). troupe's own events never
use it, which the topic rule enforces.

A test checks that `aggregate.TOPICS` and the schema's topics agree, both ways.

### D7. `native` is removed; engine records live only in the transcript

`native` goes from `init`, `turn`, `tool_call` and `result`, and from the Python types. The host already refuses
unknown fields, so a runner still sending it is a protocol violation. Fixtures and recordings lose their `native`
fields; the Claude Code mapping in `docs/runners.md` says `system/init` maps to `init` with the engine's name,
version and model, and the whole record stays in the transcript.

The contract stays at version 1, changed in place: the only runner is in this repository, and pre-alpha has no
compatibility promise. The change is listed as **BREAKING** in the proposal and the runner docs' history.

*Alternatives.* The runner publishing a schema for its native records would pin troupe to a vendor's format: Claude
Code adds stream-json fields between releases, so a closed schema would turn every Claude Code upgrade into failed
runs. Leaving `native` open breaks the rule this change exists for. The transcript already holds every native record,
unchanged and stored by hash, so nothing is lost.

### D8. Small closures

- `successResponse.result` is `oneOf` the four method result schemas (`initialize`, `run/start`, and the empty
  result for `run/cancel` and `shutdown`). They're disjoint, since each is closed.
- `usage` names `inputTokens`, `outputTokens`, `cacheReadTokens` and `cacheWriteTokens`, each an optional
  non-negative integer. The Claude Code runner (#55) maps Claude Code's cache counters onto the last two.

## Risks / Trade-offs

- [Editors and other validators may handle `$dynamicRef` poorly] → It's standard 2020-12 and `jsonschema` handles it
  (prototyped). #60 checks the YAML language server before relying on it for actor files, and can generate a bound
  schema per runner if it doesn't.
- [The walker is home-made and could miss a construct] → Its own tests cover each rule with a bad schema, and it
  fails closed: an unknown keyword that holds subschemas is walked, and a node it can't classify fails.
- [Detail renames at about 60 raise sites] → Mechanical, and D4's hook fails any test that raises a code with a key
  its schema doesn't define, so a missed site shows up as a failing test, not as drift.
- [Events recorded before this change carry snake_case error details and `native`] → Reads don't validate payloads
  at run time, so old events still read. There are no theatres outside development to migrate (pre-alpha).
- [Test-only validation misses a code path no test exercises] → The same is true today for messages. The guard
  also records every code constructed during the session, and at the end of a full run (every test path, no `-k`
  or `-m` selection) fails if a catalogued code was never raised, so each details schema is exercised by real code.
  A partial run skips that check. Any code found unexercised gets a test in this change.

## Migration Plan

None for users: pre-alpha, and the only runner is in this repository. In the repository, the scripted runner's
fixtures and recordings are updated in the same change as the contract.
