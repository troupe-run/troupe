# Proposal

Issue: troupe-run/troupe#70. Decision: #7, with the owner's additions when it closed (2026-10-13): schema-driven for
everything, `$schema` in config files, and **strict schemas**: every object closed, every value typed, no bare
`object`, no "any", no open bags; a place that genuinely varies gets a schema of its own. Blocks #60 (the config
model), which should start from a rule that is already enforced, not one it has to retrofit.

## Why

Every schema troupe publishes is meant to be the source of truth, but six fields on main accept any JSON object:
an event's payload, error and notice `details`, a runner's `options` (in `run/start` and in `perform`'s request),
a run event's `native` detail, and a JSON-RPC success `result`. Each is a hole where nothing can check what troupe
writes or reads, where editors can't complete, and where a typo passes as data. Nothing stops the next schema from
adding another. The config model is about to add many more schemas, so the rule has to exist, and be checked,
first.

## What Changes

- **A strictness check over every schema troupe ships**, in `protocol/` and in each plugin. It fails on: a schema
  that is `true` or `{}`; a value with no type; an object that isn't closed (by its own `additionalProperties:
  false`, or by an enclosing `unevaluatedProperties: false`); a map whose keys or values aren't typed; an array
  with no `items`. It is tested against hand-made bad schemas, so it can't pass by checking nothing.
- **Event payloads get a schema per topic.** `Run.Started`, `Run.Reported` and `Run.Ended` each get a state schema
  in `protocol/schemas/events/`, matching what is recorded today, including the `eventsourcing` library's own
  fields. The event-record schema picks the state schema by the event's topic, and an unknown topic doesn't
  validate. Opaque bytes (`state_b64`) stay for payloads that aren't JSON, as the library's recorder contract
  requires; troupe's own events never use them.
- **Every error and notice code declares its details.** The error and notice schemas list every code, each with a
  closed schema for its `details` (or none allowed). Codes and their details become protocol, and the Python
  catalogues (`CODES`) are checked against the schemas both ways. Detail keys become camelCase, like the rest of
  the protocol. **BREAKING** for anything reading the old snake_case detail keys (nothing outside this repo does).
- **The runner contract lists its own error codes** (`runner.parse-error`, `runner.invalid-params` and the rest
  the scripted runner already sends), so a runner's protocol errors validate. A runner's own codes, such as
  `scripted.invalid-script`, are published by the runner.
- **A runner publishes a schema for its options, and for its own error codes.** The contract's `options` field
  becomes an extension point (a JSON Schema `$dynamicRef`) whose default accepts only `{}`; a runner's published
  schema fills it. The scripted runner publishes both. The host still passes options through unchanged at run time;
  validating them at run time, and how troupe obtains an installed runner's schemas, is the config model's call
  (#60), which is the first thing that needs them.
- **`native` is removed from run events. BREAKING** for the runner contract, changed in place (no runner outside this
  repo exists). Engine-specific detail lives only in the transcript, which already holds the engine's
  every record, unchanged and stored by hash. Run events stay engine-neutral and closed.
- **The runner contract is renumbered version 0, the draft**: it changes in place, with no compatibility
  promise, until troupe commits to version 1 (design D9). **BREAKING** for a runner offering version 1; the only
  one is in this repo.
- **A JSON-RPC success result is one of the contract's result schemas**, not any object.
- **`usage` names its counters:** `inputTokens`, `outputTokens`, `cacheReadTokens` and `cacheWriteTokens`.
- Tests: in the test suite, every error, notice and recorded event troupe produces is validated against its
  schema as it's made, so a details or payload shape that drifts fails the test that produced it.

## Capabilities

### New Capabilities
- `protocol`: the rules every schema in `protocol/` and every plugin's published schema follows: JSON Schema
  draft 2020-12, strict (closed objects, typed values), extension points with closed defaults, and the codes and
  event payloads catalogued in the protocol.

### Modified Capabilities
- `runner-protocol`: run events no longer carry `native`; engine-specific detail is only in the transcript or the
  runner's options; a runner publishes its options schema and its own error codes; the contract lists its protocol
  error codes; a success result matches its method's result schema.
- `scripted-runner`: publishes the schema for its options and its error codes, and its fixtures carry no `native`.
- `event-store`: a recorded troupe event's payload validates against its topic's state schema.
- `cli`: error data, including `details`, validates against the error's code-specific schema.

## Impact

- `protocol/schemas/`: every file touched; new `events/` directory; `runner/` gains the contract's error codes.
- `plugins/runner-scripted/`: new `schemas/` (options, errors); fixtures and recordings lose `native`.
- `packages/troupe`: `core/errors.py` and `core/notices.py` (catalogues checked against the schemas; detail keys
  renamed at every raise site, about 60), `core/runners/protocol.py` (no `native`; typed `usage`), the runner
  conformance suite (options and error schemas).
- Tests: a new strictness test; one shared registry of every schema; an autouse fixture validating errors, notices
  and recorded events; existing schema tests updated.
- Docs: `protocol/README.md`, `docs/runners.md` (no `native`; the Claude Code mapping keeps `system/init` in the
  transcript; the contract's error codes; publishing a runner's schemas).
- No new runtime dependency: validation stays in the tests, as it is today (runner-contract D11).
