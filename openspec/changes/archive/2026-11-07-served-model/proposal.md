# Proposal

## Why

`init` names the model a run asked for, and it has to come first, before any model has answered. A service names
the model that actually answered in each response, often a dated snapshot of an alias, and a compatible host may
serve another model under the name asked for. By then `init` has gone, so the OpenAI runner can only say so in a
`log` at `info`, once, and lineage and later reviews can't tell from the events which model did the work (#295, found
building the OpenAI runner: its design D12, gap 5). Claude Code has the same gap: each assistant message names its
model, and its result's `modelUsage` lists every model the run used, including ones its subagents and tools ran on.

## What Changes

- **A new run event, `served_model`**, with one field, `model`: a model that answered part of the run, as the engine
  or service named it, when it isn't the model `init` named. A runner sends it the first time each such model
  answers, before the event that reports that answer, so it's in the stream where it happened and is kept even when
  the run is cancelled before its `result`. It never names `init`'s model and never repeats a model; troupe treats
  either as a protocol violation, as it does a `tool_result` with no `tool_call`. `model` has the same shape as
  `run/start`'s `runtime.model` (1 to 256 characters, no control characters); a runner told of a name outside that
  shape sends a `log` warning instead.
- **`oversized.originalType`** and the SDK's event types gain `served_model`; `troupe logs` shows it as one line.
- **The OpenAI runner** sends `served_model` in place of its `info` log when a response's `model` differs from the
  runtime's.
- **The Claude Code runner** sends `served_model` for an assistant message whose `message.model` isn't `system/init`'s
  model (leaving out Claude Code's `<synthetic>`, which marks a message it made itself), and, just before `result`, for
  each model in `modelUsage` not yet reported.
- **The Ollama runner** sends `served_model` when an answer's `model` isn't the one it asked for. Ollama echoes the
  name today, so this is a guard, not a fix.
- **The scripted runner's options schema** gains a `served_model` event step, since it lists each event a script may
  send (found applying: its test that the steps cover every runner event type).
- A runner contract change, released as a protocol change. Version 0 is the draft and changes in place; an older
  troupe reading a newer runner's `served_model` refuses it, as it would any unknown event.

Out of scope: per-model usage or cost (#292, #293 change `result`'s counts), showing served models in `troupe status`'s
run summary (the events and `troupe logs` carry them; a summary field is a follow-up if reviews want it), and
normalising names (`claude-opus-5-5[1m]` against `claude-opus-5-5` is reported as Claude Code names them).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runner-protocol`: a new requirement for the `served_model` event, and its rules (once per model, never `init`'s,
  never after `result`, the model's shape).
- `actor-runners`: the host treats a `served_model` naming `init`'s model or a model already reported as a protocol
  violation. An oversized `served_model` is kept out of line like any other event, under the existing requirement.
- `openai-runner`: a response's differing model is a `served_model` event, not a `log`.
- `claude-code-runner`: assistant messages' and `modelUsage`'s models map to `served_model`.
- `ollama-runner`: an answer's differing model maps to `served_model`.

`cli` needs no delta: its requirements already show "a line for each event", which covers the new type.

## Impact

- `protocol/schemas/runner/run-event.schema.json` (and troupe's carried copy): the `served_model` definition, both
  `oneOf` lists, `oversized.originalType`. The client and event schemas reach it through `hostEvent`, unchanged.
- `packages/troupe-plugin-sdk`: `ServedModelEvent`, `EventType`, `EVENT_TYPES`.
- `packages/troupe`: the host's checks (`core/runners/host.py`), the client's `HostEvent` (`core/client/messages.py`),
  `cli/render.py`, the generated event reference
  (`docs/prompt-book/events.md`).
- `plugins/runner-openai` (`loop.py`), `plugins/runner-claude-code` (`mapping.py`, fixtures' expected events),
  `plugins/runner-ollama` (`conversation.py`), each with tests and README mapping rows.
- `plugins/runner-scripted`: a `served_model` event step in its options schema.
- `contributing/runners.md`: the events table and the three mapping tables.
- `protocol/CHANGELOG.md` is written by the release; the commit is `feat(runner-protocol): ...`.
- In flight on the same files: #292, #293, #294 and #296 (contract changes to `result` and transcripts), #289 (the
  Ollama runner's model moves to the runtime), and #291 (an LM Studio runner, which should send `served_model` too).
  Whichever merges second rebases; none decides anything here.
