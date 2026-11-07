# Design

## Context

The run events are closed (`additionalProperties: false`) and listed in one `oneOf` in
`protocol/schemas/runner/run-event.schema.json`, mirrored by the plugin SDK's event classes (`troupe_plugin_sdk.runner`)
and checked against the schema by tests. The host (`core/runners/host.py`) validates each event and enforces the
relational rules: `init` first, `seq` without gaps, no event after `result`, a `tool_result` only for an earlier
`tool_call`. `init.engine.model` is the only place a model appears today.

What each engine says about the model that answered, from the code and recordings on main:

| Runner | What it asked for | What says which model answered |
|---|---|---|
| OpenAI (Responses API) | the runtime's model | each response's `model` (parsed into `Reply.model`); today a `log` at `info`, once (`loop.py`) |
| Claude Code | `system/init`'s `model` (what Claude Code resolved) | each `assistant` record's `message.model`, and the `result` record's `modelUsage` keys. Every recorded fixture shows `claude-haiku-5-5` throughout; the error fixtures' assistant records are `<synthetic>` and their `modelUsage` is empty |
| Ollama (`/api/chat`) | the options' model | each answer line's `model`; every recording echoes the name asked for |
| scripted | none | whatever the script sends |

Version 0 of the contract is the draft and changes in place (spec: runner-protocol, "Version 0 is the draft
contract"), so a new event type needs no version or capability negotiation.

## Goals / Non-Goals

**Goals:**

- One field, defined once in the contract, that says which other model answered, recorded where it happened.
- The rule "once per model, never `init`'s" decided in one place in the SDK, and enforced by the host.

**Non-Goals:**

- Per-model usage or cost. Claude Code's `modelUsage` has per-model counts, but `result.usage` is being reworked by
  #293 (what `inputTokens` counts) and #292 (estimated cost); splitting it by model belongs with them.
- A field on the run summary (`troupe status`). The events, `troupe logs` and `Run.Reported` in the event store carry
  it; a projection can be added when a review needs it, without a contract change.
- Matching names that differ only in decoration (`claude-opus-5-5[1m]` against `claude-opus-5-5`, an alias against
  its snapshot). Refuse rather than guess: the runner reports what the engine said.

## Decisions

### D1. A new event, `served_model`, not a field on `result` or a later `init`

The issue left three places open. Chosen: a new event type, `served_model {model}`, sent the first time each other
model answers.

- **On `result`** (say `result.servedModels: [...]`): one place, and close to Claude Code's `modelUsage`. Rejected
  because a run that's cancelled, times out or crashes sends no `result`, and those runs did work too: the record of
  which model did it would be lost exactly when a review most wants it. It also can't say *when* a model changed, so a
  mid-run fallback (Claude Code's `--fallback-model` on overload) reads the same as one at the start.
- **A later `init` amendment** (a second `init`, or an `init_update`): `init` is seq 0 and exactly once, and every
  reader takes the run's runner and engine from it (`runs/projections.py`). Amending it makes every reader merge two
  events to answer "what did this run use", and makes `init` mean "the first of several".
- **A `log` with a structured shape**: `log` is free text for diagnostics. Giving one kind of log a schema makes logs a
  tagged union by convention, which the strict-schema rules exist to stop.

A new event costs a little more where events are listed (the `oneOf` lists, `oversized.originalType`, the SDK's
`EventType`, `troupe logs`' renderer, the generated event reference), and nothing in the outcome: `derive_outcome`
reads `result`, the effect check and the exit, not the event list.

The name is `served_model`, in the snake_case of `tool_call`, saying what it records; its one field is `model`, as on
`init.engine`.

### D2. Only models other than `init`'s, once each

The event exists for the difference; the asked-for model is already on `init`. Sending it for `init`'s model too would
make every run carry a redundant event, and sending it on every response would make a long run carry hundreds. Once
per distinct model is enough for lineage to answer "which models did this work", and the first one's position says
when it started. With no `engine.model` on `init`, every model that answers is "other", so a runner that couldn't
name its model up front still records what served it.

The host enforces both halves (a repeat, or `init`'s model, is a protocol violation), as it does the `tool_result`
pairing: a contract rule that nothing checks is a claim. It keeps the set of models reported in the run beside its
set of tool call ids.

### D3. The model's shape is the runtime model's

`model` uses `MODEL_PATTERN` (1 to 256 characters, no control characters), the shape `run/start`'s `runtime.model`
already has, so a served name and an asked-for name are the same kind of value and both fit in one line of `troupe
logs`. The schema says it with `pattern` and `maxLength`; the SDK's `ServedModelEvent` uses the same constant.

A service's `model` is outside troupe's control, so a runner can be told a name that doesn't fit. Truncating an
identifier would record a model that doesn't exist; leaving it out silently would hide that something answered.
The runner sends a `log` warning saying the service named a model troupe can't record, with the name cut by the
SDK's `fit` as any log message is, and no `served_model`. This is the one place the old `log` survives.

`init.engine.model` keeps its looser shape (`minLength: 1`); tightening it is a separate change, since it would refuse
runs that validate today.

### D4. The SDK decides, the runners map

`troupe_plugin_sdk` gains `ServedModels`: built with the asked-for model (or None), its `note(model)` returns what to
send for a reported name: nothing (empty, `init`'s, or already sent), a `served_model` body, or a `log` warning body
(bad shape). Bodies carry `type` and fields but no `runId` or `seq`, because each runner numbers events its own way:
the OpenAI and Ollama runners take a `seq` from `EventNumbering` as they send, and the Claude Code mapping returns
bodies that `runner.py` numbers later. One class holds the rule, and each runner only says where names come from:

- **OpenAI** (`loop.py`): `_count` calls `note(reply.model)` for each reply, replacing `_noted_model` and its `log`.
  `_count` runs before `_send_turn` and `_ended`, so the event lands before the reply's `turn`, tool calls or
  `result`.
- **Claude Code** (`mapping.py`): `_init` builds `ServedModels` from `system/init`'s `model`. `_assistant` calls
  `note` for `message.model` first, skipping `<synthetic>`; `_result` calls it for each `modelUsage` key in order,
  before the permission-denial logs. `<synthetic>` is skipped in the mapping, not the SDK: it's Claude Code's marker,
  and the SDK stays engine-neutral (spec: runner-protocol, "The contract is not specific to one engine").
- **Ollama** (`conversation.py`): `_Answer` gains `model`, read from the answer's lines (the first non-empty one);
  `note` runs when the answer ends, before its `turn` or the `result`.

A record whose `model` isn't a string is treated as naming none, as the mappings already treat a missing optional
field; it isn't a protocol matter, and the transcript keeps the record.

### D5. Tests and fixtures

- SDK: `ServedModels` unit tests (each branch), and a hypothesis test that over any sequence of names it emits each
  name outside `init`'s at most once and only names that match `MODEL_PATTERN`.
- Schema: the strictness test covers the new definition; an SDK-mirror test checks `ServedModelEvent` against the
  schema, as for the other events.
- Host: violation tests for `init`'s model and a repeat, driven through the scripted runner (which can send any
  valid event), and a run whose `served_model` is oversized is kept out of line like the others.
- OpenAI: the existing `test_a_model_other_than_the_one_asked_for_is_noted_once` becomes a `served_model` test on the
  fake endpoint; a run whose responses name the runtime's model has none (the recorded `gpt-6-luna` and `qwen3.5:4b`
  fixtures already answer as asked, so their expected events don't change).
- Claude Code: mapping tests from records built on the recorded shapes (a fallback `message.model`, `<synthetic>`,
  a `modelUsage` with an extra model). The recorded fixtures' expected events don't change, which itself pins that
  `<synthetic>` and init's own model report nothing.
- Ollama: a fake answer whose lines name another model; the recorded fixtures don't change.
- The scenario's `gpt-6-luna-2026-03-05` is illustrative of OpenAI's dated snapshot names, not a recording; tests
  that use it say they're built.

## Risks / Trade-offs

- [Old troupe, new runner: an older troupe refuses `served_model` as an unknown event, crashing the run] → Version 0
  promises no compatibility, and our runners ship with troupe from this repository; the protocol release notes the
  new event. A third-party runner on version 0 accepts the same draft terms.
- [Claude Code's names differ from `init`'s only in decoration, so every run reports one `served_model`] → It's
  true that the names differ, and it costs one event per run. If it proves noisy, normalising is a mapping change in
  the Claude Code runner, not a contract change.
- [A runner forgets a model] → Nothing can check what an engine didn't report. The host checks only what's sent;
  the runners' tests pin where names come from.
- [Parallel contract changes (#292, #293, #294, #296) and runner changes (#289, #291) touch the same schema and
  runner files] → All are additive; whichever merges later rebases. #291's LM Studio runner should adopt
  `served_model` when it lands (say so on #291 once this merges).

## Migration Plan

None for data: recorded runs have no `served_model`, and every reader already accepts a run without one. The schema
change, the SDK, the host and the three runners land in one pull request, so no runner sends the event before troupe
accepts it. Rollback is reverting that pull request; a run recorded meanwhile with `served_model` would then fail to
validate, which is acceptable pre-alpha.
