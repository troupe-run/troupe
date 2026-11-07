# Design: a run event for content an engine lost while the run carried on

## Context

See proposal.md, Why. The current state this builds on:

- `protocol/schemas/runner/run-event.schema.json` has seven runner event types in `$defs/event`, the same seven plus
  `oversized` in `$defs/hostEvent`, and the seven again in `$defs/oversized.originalType`. Every event is closed
  (`additionalProperties: false`), and optional fields are left out, never null.
- `$defs/retry` already has a closed `reason` list ending in `other`. The in-flight #296 change (`failure-reason`)
  gives `result` a closed `reason` list too, with `other` for an unlisted failure and no extension point (its D3).
- The SDK (`troupe_plugin_sdk.runner`) defines one frozen dataclass per event, `EVENT_TYPES`, `EventType` and
  `parse_event`. `troupe_plugin_sdk.events` has `EventNumbering` (the run's `seq` counter and limits) and `fit`
  (cut a summary field to the summary limit and the maximum event size). The SDK's drift test compares each type's
  fields with the schema.
- Core's runner host parses each event through the SDK, checks `seq`, `init` first and nothing after `result`,
  writes an `oversized` stand-in for an event over the size limit, and passes it on. The runs aggregate records it as
  `Run.Reported`, whose payload is `{lineage, timestamp, seq, event}` with `event` referencing `$defs/hostEvent`. So a
  new type in `hostEvent` is recorded with lineage with no change to recording.
- The CLI's `render_event` has one summary per type and shows an empty summary for a type it doesn't know.
- The engines this has to fit, for #308 and #310:
  - Claude Code writes a `system` record with `subtype: "compact_boundary"` and
    `compact_metadata: {trigger, pre_tokens}` when it compacts. It reports the size before, not after.
  - Own-loop runners (Ollama, OpenAI-style) hold the conversation as a list of messages, so they know message counts
    exactly, and they know the prompt's token count from the last request (`prompt_eval_count`,
    `usage.input_tokens`). They don't know the size after until the next request.

## Goals / Non-Goals

**Goals:**
- One event shape that Claude Code's compaction and #310's runner-side compaction both fit, without either having to
  invent a number it doesn't have.
- A closed vocabulary, like `retry.reason` and #296's `result.reason`, that later gates can match on.
- Runners send it with one SDK call, fitted to the run's limits like every other summary.

**Non-Goals:**
- Any host behaviour beyond recording and showing it: no notice, no outcome change, no gate. The decision leaves
  that for later, and the event carries enough for it.
- A cumulative "how much was lost in this run" figure on `result` or the run summary. A reader can sum the events.
- Detecting a loss a runner doesn't report. The host can't see inside an engine. Each runner's change (#308, #310)
  is responsible for reporting every loss it can observe.

## Decisions

### D1. A new event type named `context`

The issue's example name. It names what's affected (the run's context: the conversation the engine works from), and
reads naturally beside `retry` and `log` in a run's logs (`context: compacted by engine`).

Alternatives: `compaction` (wrong for a truncation); `context_lost` (snake_case like `tool_call`, but "lost" is wrong
for a compaction that keeps a summary); a `log` with a fixed code, or a field on `result`, were both rejected by the
decision.

### D2. `kind`: `compacted`, `truncated`, `other`

The decision named "compacted, truncated". `compacted` is earlier content replaced by a summary of it: detail lost,
gist kept (Claude Code's compaction, #310's summarising). `truncated` is earlier content dropped outright (what
Ollama does past `num_ctx`, and what #310's "drop old tool output" does). The difference matters to a gate: after a
truncation, the engine may not know what it was told at all.

"Truncated" here is about the conversation's earlier content. A cut answer at the output limit is not a `context`
event: the decision says that ends the run with `output-limit` (#309).

### D3. A kind the list has no entry for is `other`; no extension point

Same rule as #296's D3 and `retry.reason`: a kind is useful only if troupe can act on it the same way for every runner,
so a runner can't add its own. `other` says "content was lost, in a way the list doesn't name", which is still
actionable ("something was lost"). The message must then say what. A runner that keeps sending `other` for the same
thing files an issue to add a kind. A kind outside the list is a schema violation, so the host ends the run as a
protocol violation, as for any malformed event. It isn't quietly turned into `other`.

### D4. `by`: `engine` or `runner`, required

Who chose what to lose differs in a way later gates and #310 care about. A runner's own compaction follows rules troupe
specifies (it keeps the character and the direction). An engine's compaction follows the engine's own rules, which
troupe can't see. Both are already known to the runner when it sends the event, so requiring it costs nothing.

Alternative: infer it from `init` (a runner with an engine means `engine`). That doesn't work: an own-loop runner has an
engine but does its own compaction.

### D5. Amounts: four flat optional counters, tokens and messages

`tokensBefore`, `tokensAfter`, `messagesBefore`, `messagesAfter`, each `integer >= 0`, each left out when unknown.
Flat names match `result`'s style (`durationMs`, `costUsd`) and keep the event one level deep. Claude Code fills only
`tokensBefore`. An own-loop runner fills both message counts and `tokensBefore` from its last request.

Messages, not turns: the issue said "tokens or turns" as an example. `result.turns` already means the engine's
round-trips, which compaction doesn't change. What compaction changes is how many messages the conversation holds,
which an own-loop runner knows exactly. Turns would also be ambiguous for a truncation that cuts a turn's tool output
but keeps the turn.

No rule that "after" is less than "before": the schema can't express it, a summary can add a message, and refusing a
real engine's odd numbers would end a run that is otherwise fine. Not requiring a pair either: Claude Code has only the
"before" figure.

Alternative: nested `before: {tokens, messages}` and `after: {...}`. It's tidier, but an empty object would then need
its own rule (`minProperties`), and it differs from every other event's shape.

### D6. Recorded and shown with no new host rule

The host already enforces everything D1 to D5 need: the schema (through the SDK's parse) for shape, `seq` order,
`init` first, nothing after `result`, and the oversized stand-in. The changes are lists: `hostEvent`,
`oversized.originalType`, core's `HostEvent` union, and one `render_event` summary:
`compacted by engine, tokens 41000 →` plus whichever counts are present (`messages 120 → 34`). The outcome is untouched,
because success already depends only on the `result`, the effect check and the exit.

No notice during `perform`: a notice is "what troupe does with it", which the issue puts out of scope. The event is in
the logs and in `perform`'s event stream, as every event is.

### D7. The SDK: `ContextEvent`, `ContextKind`, and `context_event(...)`

`troupe_plugin_sdk.runner` gains `ContextKind = Literal["compacted", "truncated", "other"]`, `ContextBy =
Literal["engine", "runner"]` and a frozen `ContextEvent(RunEvent)` with `TYPE = "context"`. It's added to
`EVENT_TYPES` and `EventType`, so `parse_event`, the scripted runner's `event` step and the drift test cover it with no
further code.

`troupe_plugin_sdk.events` gains `context_event(numbering, kind, by, message, *, tokens_before=None, tokens_after=None,
messages_before=None, messages_after=None) -> ContextEvent`. It checks the kind and `by` before taking a `seq`, so a
refused call leaves the counter as it was. It leaves out each `None` count and fits `message` with the existing `fit`
(summary limit, then the maximum event size), then builds the type, so the dataclass's own checks run too. It sits
beside `fit` and `EventNumbering` because it's the same job they do for tool events. Runners send the result with
their existing writer.

Alternative: no helper, only the type. #308 and #310 would then each write their own fitting, which is the duplication
the issue asks the SDK to remove.

### D8. Released as an additive protocol and SDK change

Commits touching `protocol/` are `feat(runner-protocol):` and the SDK's are `feat(plugin-sdk):`, with no `!`. A runner
that never sends `context` still conforms, and the contract's version stays 0. release-please bumps each component's
minor version (`bump-minor-pre-major`). An older troupe would refuse a `context` event from a newer runner, but the
contract is version 0, which promises no compatibility, and there are no third-party runners yet.

## Risks / Trade-offs

- [#296 edits the same schema and SDK module] → the two touch different `$defs` and different dataclasses, so the
  conflict is only in the shared lists (`event`, `hostEvent`, `originalType`, `EVENT_TYPES`, `EventType`, `HostEvent`,
  `render_event`). Whichever merges second rebases, then runs the full check and fixes it in a new commit.
- [A runner reports a loss as `log` instead] → the contract doc says when to send `context`, and #308 and #310 each
  have a test that their loss produces one. The host can't detect an unreported loss (non-goal).
- [`other` becomes a dumping ground] → D3's rule to file an issue, and both known sources (Claude Code, #310) map to
  `compacted` or `truncated`.
- [Token counts mean different things per engine (with or without cached tokens, the system prompt)] → the counts are
  "as the engine or runner reports them", like `result.usage`. #293 (`input-tokens-meaning`) is pinning down what
  `inputTokens` means, and a later change can apply the same meaning here.

## Migration Plan

One pull request: schema and packaged copy, SDK, core's union and rendering, docs, and tests together. No runner
sends the event yet, so nothing recorded changes. There are no theatres to migrate. Rollback is reverting it.
