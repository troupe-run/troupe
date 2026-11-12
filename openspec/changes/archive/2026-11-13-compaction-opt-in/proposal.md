# Proposal: actors opt in to compaction when their engine's context fills

## Why

Decision #279 (point 1) made failing with `context-length` the default when a run's engine runs out of context, and
#308 brought the Claude Code runner into line. Failing loses nothing, but it stops long tasks on a small window, such
as a local model with a 16k window that reads a few files. Compaction lets those tasks finish, but it changes what
the model sees, so an actor or a policy has to choose it explicitly. It's never a default. troupe-run/troupe#310
builds that choice. #307's `context` event, now on main, reports each compaction.

## What Changes

- **A runner-agnostic actor setting**, `onContextFull`: `fail` (the default when absent) or `compact`. It sits beside
  `workspace` and `effects` in the actor's config, set with `troupe config set actors.<name>.onContextFull=compact`.
- **A policy setting**, `TROUPE_POLICY_COMPACTION`: `actors` (the default: each actor's setting decides), `all`
  (every actor compacts unless its own setting says `fail`), or `none` (no actor compacts, and a run for an actor
  whose setting says `compact` is refused before it starts, naming the policy). A malformed value is
  `policy.invalid-value`.
- **`run/start` gains a required `onContextFull`**, the value core works out from the actor and policy. Every runner
  receives it, and none reads it from its options. This is a protocol change: a runner built before it rejects the
  new field, and the contract is version 0, which promises no compatibility.
- **The Ollama and OpenAI runners compact their own conversation** when it's `compact`. They replace old tool results
  with a short stub, oldest first, and keep the call. The character, the direction, every assistant message and the
  latest turn's tool results are never touched. This needs no model call, so nothing extra counts towards the token
  budget or turn limit. The Ollama runner compacts before a request that wouldn't fit its known window, and after a
  refusal. The OpenAI runner, which doesn't know the model's window, compacts after a `context_length_exceeded`
  refusal and sends the request again. Each compaction is a `context` event with `kind` `truncated`, `by` `runner`,
  and the message counts. When nothing more can be stubbed, the run ends with `context-length`, as today.
- **The SDK holds the shared part** (`troupe_plugin_sdk.compaction`): which results to stub, the stub's wording, the
  size estimate and the `context` event. Each runner maps its own message shapes onto it.
- **The Claude Code runner lets Claude Code compact** when it's `compact`. It writes `autoCompactEnabled: true` in its
  per-run settings file, and removes `DISABLE_AUTO_COMPACT` from Claude Code's environment so the person's variable
  can't silently override the actor's choice. It maps Claude Code's `system/compact_boundary` record to a `context`
  event (`compacted`, `by` `engine`, `tokensBefore` from `pre_tokens` and `tokensAfter` from `post_tokens`). It maps the `system/status` records with
  `compacting` and `compact_result` to debug logs, not to events, because no content is lost until the boundary. A
  compaction that fails still ends the run with `context-length`, as #308 maps it.
- **Fixtures**: the Claude Code capture tool gets a compaction mode. Its stand-in API answers Claude Code's compaction
  request with a summary, and the tool refuses to write the fixture unless it saw a compaction. The opposite check,
  for the context-limit fixtures, is unchanged. The Ollama and OpenAI runners get fixtures of a conversation that is
  compacted and then finishes.
- **The LM Studio runner** (merged while this was in review) doesn't compact yet: told `compact`, it sends a `log`
  warning after `init` saying so, and a full context ends the run with `context-length`. With #394, which this change
  closes too, every prediction sets LM Studio's `contextOverflowPolicy` to `stopAtLimit`, so LM Studio never drops
  content silently. Compacting between `act()` rounds is a follow-up Feature (owner, 2026-11-12).
- **Docs**: the actor reference, the runner docs and the policy reference say what `onContextFull` and
  `TROUPE_POLICY_COMPACTION` do, and that compaction changes what the model sees.
- **The run's start records** its `onContextFull` and where it came from (`default`, `actor` or `policy`), so a
  run's history says whether it was allowed to compact.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `config`: an actor has an optional `onContextFull`, `fail` or `compact`.
- `policy`: the `compaction` setting, `actors`, `all` or `none`, read through the seam.
- `runner-protocol`: `run/start` carries `onContextFull`, and a runner told `fail` never compacts.
- `runs`: core works out each run's `onContextFull` from the actor and the policy, records it and where it came from
  in the run's start, and refuses a run that policy forbids.
- `plugin-sdk`: the SDK chooses which tool results to stub and builds the stub and the event.
- `ollama-runner`: compacts before a request that wouldn't fit, and after a refusal, when told `compact`.
- `openai-runner`: compacts after a `context_length_exceeded` refusal and sends the request again, when told
  `compact`.
- `claude-code-runner`: compaction is off unless the run says `compact`, and a compaction is a `context` event.
- `lm-studio-runner`: every prediction stops at the context length (#394), and a run told `compact` says the runner
  doesn't compact.

## Impact

- `protocol/schemas/runner/run-start.schema.json` and its packaged copy, the actor config schema, and the SDK's
  `RunStartParams`. Core's runner host and `perform` resolve the value. `core/policy.py` gets its first setting that
  isn't a boolean.
- `plugins/runner-ollama` (`conversation.py`), `plugins/runner-openai` (`loop.py`), `plugins/runner-claude-code`
  (`command.py`, `mapping.py`, `tools/capture_claude.py`), and the scripted runner, which accepts the field and
  ignores it because it has no engine.
- New fixtures in three runners. The pages under `docs/` on actors, runners and policy.
- No new spec, so no change to infrastructure's `oob/troupe-spec-purposes.json`.
- Out of scope: gates acting on compaction (later, per #310), and summarising with a model call (see design, D5).
