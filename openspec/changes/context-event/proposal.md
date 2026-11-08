# Proposal: a run event for content an engine lost while the run carried on

Issue: [troupe#307](https://github.com/troupe-run/troupe/issues/307), from Decision
[troupe#279](https://github.com/troupe-run/troupe/issues/279), point 2 (owner, 2026-11-07).

## Why

Decision #279 settled that an engine never loses or cuts content without the run saying so. When the loss ends the
run, #296's failure reasons name it (`context-length`, `output-limit`). When content is lost and the run carries on,
such as opt-in compaction (#310) or Claude Code compacting (#308), nothing names it today. A runner can only send a
free-text `log`, and the transcript holds the engine's own record. So the host, lineage and later gates can't act on
it the same way for every runner. The decision chose a named run event, and rejected a `log` with a fixed code (easy
to miss, loosely typed) and a field on `result` (only known at the end, and not tied to when it happened). The
contract is still version 0, the draft that changes in place, so this is the cheapest time to add it.

## What Changes

- **A new run event type, `context`** (design D1). A runner sends one each time its engine, or the runner itself,
  loses or compacts content of the conversation and the run carries on. It's a run event like the others: numbered in
  `seq`, after `init` and before `result`, and never ends the run itself.
- **What happened, from a closed list** (D2): `kind` is `compacted` (earlier content summarised), `truncated`
  (earlier content dropped outright) or `other`.
- **A kind the list has no entry for is `other`**, and the event's `message` says what happened. A runner can't add
  its own kinds, matching how #296 handles failure reasons: a kind is only useful if troupe can act on it the same
  way for every runner. A runner that keeps sending `other` files an issue to add the kind to the list (D3).
- **Who did it** (D4): `by` is `engine` (the engine did it on its own, as Claude Code compacts) or `runner` (the
  runner did it to the conversation it holds, as #310's own-loop compaction will).
- **How much, where known** (D5): `tokensBefore`, `tokensAfter`, `messagesBefore` and `messagesAfter`, each optional
  and left out when the engine or runner doesn't know it. There are no nulls and no guesses.
- **A required `message`**: what happened, in words, fitted to the run's limits like every other summary.
- **Recorded the same way for every runner** (D6): troupe records a `context` event as it records every run event, as
  a `Run.Reported` with full lineage, and kept out of line as an `oversized` event when it's too large. `troupe logs`
  shows its kind, who did it and the amounts. It doesn't change the run's outcome. What troupe does with it (a gate,
  an escalation, a notice) is later.
- **The SDK helps runners send it** (D7): a `ContextEvent` type with a `ContextKind` list, and a helper that builds a
  numbered `context` event with its message fitted to the run's limits, so #308 and #310 each call one function.

Out: sending it from each runner (#308 for Claude Code, #310 for opt-in compaction); the compaction setting and
runner-side compaction (#310); what troupe does with the event (gates, escalation, notices: later); losses that end
the run, which #296's reasons name.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runner-protocol`: the event types gain `context`, and a new requirement says when a runner sends it and what it
  carries (its kind from a closed list, who did it, the optional amounts and its message).
- `plugin-sdk`: the SDK defines the `context` event's type and a helper that builds one numbered and fitted to the
  run's limits.
- `runs`: a `context` event is recorded with lineage like every run event, shown by `logs`, and leaves the outcome
  as it was.

## Impact

- **Protocol:** `protocol/schemas/runner/run-event.schema.json` (`$defs/context`, in `event`, `hostEvent` and
  `oversized.originalType`) and troupe's packaged copy under `packages/troupe/src/troupe/protocol/`. Additive: a
  runner that never sends `context` still conforms. Released as a protocol `feat`, which bumps the protocol's minor
  version before 1.0.
- **SDK:** `troupe_plugin_sdk.runner` (`ContextEvent`, `ContextKind`, `EVENT_TYPES`, `EventType`) and
  `troupe_plugin_sdk.events` (the helper). Released at the SDK's own version, as a `feat`.
- **Core:** `troupe.core.client.messages.HostEvent` and the CLI's `render_event`. The runner host needs no new rule:
  it already parses events through the SDK and records them in order.
- **Scripted runner:** its options schema gains a `context` event step, so a script can send one. Its code is
  unchanged: the `event` step already sends any event the SDK parses. A test drives a `context` event through it end
  to end.
- **Docs:** `contributing/runners.md` (the run events table, and a note on when to send `context`), the generated
  event reference (`docs/prompt-book/events.md`), and `protocol/README.md` if it lists event types.
- **Parallel work:** #296 (`failure-reason`) also edits `run-event.schema.json` and the SDK's event types. Whichever
  merges second rebases. The two touch different `$defs`, so the conflict is in the shared lists.
- **No spec is added or removed and no Purpose changes,** so infrastructure's `oob/troupe-spec-purposes.json` needs no
  update.
