# Design: actors opt in to compaction when their engine's context fills

## Context

See proposal.md, Why. What this builds on, as main has it on 2026-11-12:

- **Actor config** (`protocol/config/actor.schema.json`) has the runner-agnostic fields `runner`, `expect`, `effects`,
  `workspace`, `runtime` and `model`, and the runner's own `options`, which only the runner's published options
  schema fills. `perform._from_config` copies `options` unchanged. `run/start` carries `effects` and `runtime` as their
  own fields. There is no runner-agnostic budget: the OpenAI runner has `maxTotalTokens`, Claude Code
  `maxBudgetUsd`, and Ollama only `maxTurns`.
- **Policy** (`core/policy.py`) is one seam with two boolean `allow_*` flags, each read from `TROUPE_POLICY_<NAME>`
  with its source. A malformed value is `policy.invalid-value`. Policy has no levels or per-actor values yet, and
  "a lower level can only tighten" isn't enforceable until it does.
- **#307's `context` event**: `kind` `compacted` | `truncated` | `other`, `by` `engine` | `runner`, a `message`, and
  optional `tokensBefore`, `tokensAfter`, `messagesBefore` and `messagesAfter`. It's sent with the SDK's
  `context_event(...)`, before any event that follows from the reduced conversation, and never ends the run.
- **Ollama runner** (`conversation.py`): holds `_messages` as pre-encoded JSON, sends the whole list on every
  request with `truncate: false`, `shift: false` and `num_ctx` set to the window (`contextLength`, or 16384 lowered
  to the model's maximum). The character is the `system` message and the direction the first `user` message. Each
  tool result is capped at `tool_budget(window)`, a named share of the window at `BYTES_PER_TOKEN` 3. A refusal
  (`CONTEXT_REFUSAL`) ends the run with `context-length`. It knows each answer's `prompt_eval_count`.
- **OpenAI runner** (`loop.py`): Responses API, `store: false`, no `previous_response_id`. `instructions` hold the
  fixed instructions and the character, and `input` starts with the direction as a `user` message. Each turn appends
  the reply's output items (including encrypted `reasoning` items) and the `function_call_output`s. A 400 with
  `code` `context_length_exceeded` is `context-length`, and isn't retried. The model's window is unknown to it.
- **Claude Code runner**: `command.build()` writes `autoCompactEnabled: false` in the per-run `--settings` file
  (#308, design D1), and starts Claude Code with `{**env, **rules.env, **ENGINE_ENVIRONMENT}`. `mapping.py` maps
  `terminal_reason` `prompt_too_long` and `blocking_limit` to `context-length`, and logs any other `system` subtype
  once at debug level as unmapped. #308's probe (Claude Code 2.1.319) showed that with compaction on, Claude Code
  compacts proactively before a request near the window and reactively after a refusal. It sends `system`/`status`
  `{"status":"compacting"}`, then `{"status":null,"compact_result":...}`. `DISABLE_AUTO_COMPACT=1` overrides the
  setting, and a loaded setting source's `env` block overrides the variable.
- **Capture tool** (`tools/capture_claude.py`): the `_ContextLimit` stand-in API, and `compaction_seen`, which makes
  the tool refuse to write a context-limit fixture when it sees compaction.

## Goals / Non-Goals

**Goals:**
- One setting, the same for every runner, that an actor or a policy sets, with `fail` the default.
- Own-loop runners that compact without losing the character, the direction or what the model just asked for, and
  report each compaction.
- Claude Code compacts only when told to, and each compaction it makes is a `context` event.
- A run that compaction can't save still ends with `context-length`.

**Non-Goals:**
- Gates or notices that act on compaction (#310 puts them out of scope).
- Summarising with a model call (D5).
- Compacting for a reason other than a full context, such as cost.
- Making policy levels or tighten-only enforceable in general. This change adds one setting to the existing seam.

## Decisions

### D1. A runner-agnostic actor field, `onContextFull`: `fail` | `compact`

**Owner's decision (2026-11-12, Q1).** The choice is about the run, not about
one runner: every runner has to honour it, policy has to see it, and lineage should record it the same way. That's
what `effects` and `workspace` already are, so it's a top-level actor field, not a runner option. An option would
need each runner's schema to repeat it, policy couldn't see it without knowing every runner's options, and nothing
would stop two runners naming it differently.

The name says when it applies and what happens: `onContextFull: compact`. The values are verbs for what the run does,
and `fail` is spelled out so a person can write the default explicitly. Under `TROUPE_POLICY_COMPACTION=all`, an
explicit `fail` means something different from leaving the field out. Absent means `fail` (only an absent input
falls through). Any other value is refused by the schema at `config set`, naming the path and the two values.

Alternatives: a runner option `compaction: true` (rejected above). A boolean `compact: true` doesn't read as "what
happens when the context is full", and leaves no room for a later value such as a summarising mode (D5).

### D2. Policy `compaction`: `actors` | `all` | `none`

**Owner's decision (2026-11-12, Q1).** Decision #279 says "per actor or by policy". The policy setting is the first one that isn't a
boolean, read through the same seam (`TROUPE_POLICY_COMPACTION`, value and source):

| Policy | Actor absent | Actor `fail` | Actor `compact` |
|---|---|---|---|
| `actors` (default) | fail | fail | compact |
| `all` | compact | fail | compact |
| `none` | fail | fail | refused before the run |

- `all` turns compaction on for every actor that hasn't said otherwise. An actor can still say `fail`, which is the
  tighter choice, so a lower level only tightens.
- `none` refuses a run whose actor asks for `compact`, with `policy.compaction-forbidden` naming the actor, the
  policy variable and the fix (set the actor's `onContextFull` to `fail`, or change the policy). It doesn't quietly
  run the actor with `fail`: the actor's config asked for something the run would not do (refuse rather than guess).
  The refusal comes before the run's start is recorded, like other checks before a worktree is made.
- A value outside the three is `policy.invalid-value`, naming the variable, the value and the accepted values.

The seam returns the value with its source, as for the flags. A typed enum setting is a small generalisation of
`_flag`.

### D3. `run/start` carries the resolved value; the run's start records where it came from

`run/start` gains a required `onContextFull`, `fail` or `compact`: the value after D2, never the actor's raw field.
The runner never sees policy (the spec says policy never comes from a request, and a runner is no different). It's
required, not optional with a default, so a host that forgot to send it fails the schema instead of a runner quietly
assuming `fail`. The SDK's `RunStartParams` gains `on_context_full`.

The run's start event records `onContextFull` and its source: `actor` when the actor set it, otherwise `policy`
when the policy is `all` or `none`, otherwise `default`. That's like the
runtime's values and where each came from, so `troupe logs` and lineage say whether a run was allowed to compact
and why. A `context` event in a run whose start says `fail` is then visibly wrong.

**A runner told `fail` never compacts.** That holds for every runner. The scripted runner accepts the field and
ignores it: it has no engine and no context.

This is a breaking protocol change, since a runner that predates it rejects the unknown field. The contract is
version 0, which promises no compatibility, and every runner is in this repo. The commit is `feat(runner-protocol)!`,
like any other required `run/start` field.

### D4. Own-loop runners stub old tool results, oldest first

**Owner's decision (2026-11-12, Q2).** When the conversation won't fit, the runner replaces the content
of old tool results with a stub, and keeps the message and the call:

> `[troupe removed this Read result to make room in the context window. Call Read again if you still need it.]`

It does this oldest first, until the estimate (D6) is at or below the target. Never touched:

- the character (Ollama's `system` message, OpenAI's `instructions`);
- the direction (the first `user` message);
- every assistant message, its text, its tool calls (with their arguments) and, for Ollama, its `thinking`;
- OpenAI's `reasoning` items (encrypted, so they can't be shortened; see Risks);
- the tool results of the latest turn, which the model hasn't read yet;
- a result already stubbed, or one already smaller than its stub.

Why stubs rather than dropping messages: both APIs require every call to have a result (OpenAI rejects a
`function_call` without its `function_call_output`), and the call's arguments still tell the model what it looked
at. Why tool results first: they are the bulk of a long run (one `Read` can be up to the tool budget), and every one
can be recovered by calling the tool again, which the stub says. Why oldest first: the model is least likely to need
them.

This is `kind` `truncated` (content dropped outright, #307 D2) with `by` `runner`. One event goes out per compaction,
not per stubbed result.

If nothing is left to stub and the conversation still won't fit, the run ends as it does today, with `error` and
`reason` `context-length`. The message adds that compaction was on and found nothing more to remove.

### D5. No model call to summarise, in this change

**Owner's decision (2026-11-12, Q2).** Summarising old turns with the run's own model would keep more than a stub, but:

- it is a model call that counts towards the budget (`maxTotalTokens`; for Ollama, a turn against `maxTurns`) and
  can itself overflow, fail or be cut;
- a small local model, the case this exists for, writes unreliable summaries, and a wrong summary is worse than an
  honest gap the model can fill by calling a tool again;
- stubbing is deterministic, so it can be tested exactly from fixtures.

Stubbing satisfies the issue's "dropping or summarising old tool output". If the owner wants summarising too, the
proposal's alternative is a second step after stubbing, `kind` `compacted`, counted towards the budget, and that
would be a new value of `onContextFull` (`summarise`) so actors opt into the extra call separately.

### D6. When each own-loop runner compacts, and how far

The SDK estimates size in bytes and converts to tokens. It calibrates the conversion from the last request whose
token count the engine reported (`prompt_eval_count`, `usage.input_tokens`), using that request's bytes. Before any
request, it uses its named default (`BYTES_PER_TOKEN`, 3, which moves from the Ollama runner into the SDK).

- **Ollama knows its window**, so it compacts **before** a request whose estimate is over a named share of the
  window (`COMPACT_AT_SHARE`, 0.85). Ollama's `num_ctx` holds the answer too, so a request filled to the brim would
  be cut as `output-limit`. It compacts down to `COMPACT_TO_SHARE` (0.5) of the window, so it doesn't compact again
  on the very next turn. It also compacts **after a refusal** (`CONTEXT_REFUSAL`) if the estimate was wrong, then
  sends the request again.
- **OpenAI doesn't know the model's window**, so it compacts only **after** a `context_length_exceeded` refusal. It
  compacts down to `COMPACT_TO_SHARE` of the input tokens of the last request that was accepted, which is the best
  known size that fits, then sends the request again.

A request sent again after a compaction is the same turn: it doesn't count towards `maxTurns`, and the refused request
used no tokens. Each compaction has to stub at least one result, so the loop can't spin: a refusal after a
compaction that stubbed nothing ends the run with `context-length`. The thresholds are named settings with their
defaults in the SDK's `defaults.py`, because both runners use them.

### D7. The shared part lives in the SDK

`troupe_plugin_sdk.compaction` holds what both own-loop runners need, so the rules in D4 and D6 have one definition:

- `Candidate`: an index into the runner's conversation, the tool's name and the result's size in bytes, plus whether
  it's in the latest turn.
- `choose(candidates, estimate_bytes, target_bytes) -> list[int]`: which results to stub, oldest first, skipping the
  protected ones. Pure, so property tests cover it: it never picks a protected result, it stops at the target, and it
  returns nothing when nothing helps.
- `stub(tool) -> str`: the stub's text, one wording for every runner.
- `Estimate`: bytes to tokens, calibrated as in D6.
- The `context` event is the existing `context_event(...)`, with `messagesBefore` and `messagesAfter` (equal, since
  stubbing removes no message), `tokensBefore` from the estimate, and a message such as "removed 7 old tool results
  (41 KB) to fit the context window".

Each runner maps its own shapes: the Ollama runner re-encodes the stubbed `tool` messages in `_messages`, and the
OpenAI runner replaces `output` in the chosen `function_call_output` items. The SDK has no conversation type, since
the two runners' messages differ and the SDK takes no position on an engine's API (plugin-sdk spec). This fits
"extract callables from day one": a third own-loop runner would reuse it unchanged.

### D8. Claude Code: the setting, its environment, and the boundary event

- `build()` writes `autoCompactEnabled` as `on_context_full == "compact"`, in the same `--settings` file, which
  ranks above every loaded setting source (#308 D1).
- **Owner's decision (2026-11-12, Q3), by D9's rule:** when it's `compact`, `build()` removes
  `DISABLE_AUTO_COMPACT` from Claude Code's environment, so a person's own variable can't silently override the
  actor's choice. It's never silent: when the variable was set, the runner sends a `log` event at level `warning`
  just after `init`, naming `DISABLE_AUTO_COMPACT` and saying the actor's `onContextFull` `compact` overrides it for
  this run. With `fail`, the variable is left alone: it can only turn compaction off, which the setting already
  does. A project settings file
  whose `env` block sets the variable can still turn compaction off. That direction is safe (the run fails with
  `context-length`), and the docs say so.
- `mapping.py` maps `system`/`compact_boundary` to `context_event("compacted", "engine", ...)` with `tokensBefore`
  from `compact_metadata.pre_tokens` when it's a non-negative integer, and the trigger (`auto` or `manual`) in the
  message. That record is when content was lost. It comes before the next turn's records, so the event precedes the
  turn's events, as #307 requires.
- `system`/`status` records with `compacting`, or with a `compact_result`, map to a debug `log` each, by name, rather
  than "isn't mapped". No content is lost until the boundary. A failed compaction (`compact_result` `failed` or
  `exhausted`) is followed by `terminal_reason` `blocking_limit` or `prompt_too_long`, which already maps to
  `context-length`.
- A `compact_boundary` in a run told `fail` is still reported as a `context` event, because something compacted
  despite the setting (say, a project's settings file). Hiding it would be worse. The event then shows the mismatch
  in the run's history.

### D9. Precedence: the run's own value beats the environment, which beats a built-in default

**Owner's decision (2026-11-12, Q3)**, a general rule, like application config: a value given for this run beats
one from the environment, which beats a default built into troupe or the engine. `onContextFull` is sent with each
run in `run/start`, so it is the run's own value. An engine's environment variable for the same choice
(`DISABLE_AUTO_COMPACT`) yields to it, and Claude Code's built-in default (compaction on) yields to both.

Where troupe has to override a value from the environment to apply the rule, it says so in the run's events (D8's
`log`), so the override is never silent. A setting troupe can't control, such as an `env` block in a project's
Claude Code settings file, isn't overridden. When it turns compaction off, the run fails with `context-length`,
which is the safe direction. The docs say so.

Policy sits outside this order. It bounds what an actor may ask for (D2) before a run's value is worked out.

### D10. Fixtures

- **Claude Code:** `capture_claude.py` gets a `--compaction` mode, the opposite of the context-limit fixtures. Its
  stand-in API answers Claude Code's compaction request (recognised by its summary prompt, as captured in the probe
  log) with a short summary. It answers the request after that with a final text answer. The fixture is captured
  through the runner's own `build()` with `onContextFull` `compact`. The tool refuses to write it unless it saw a
  `compact_boundary` record, and it records the stand-in's request count like the others. Two fixtures:
  `compaction-proactive` (a 990,000-token turn) and `compaction-reactive` (a refusal, then a compaction). If the
  boundary record's shape differs from what D8 assumes, the mapping follows the captured record, and the design is
  updated in the same commit.
- **Ollama:** a `context-compacted` fixture captured from real Ollama with a small `contextLength` (as
  `context-overflow` is). A run reads several files, gets compacted and finishes `ok`. Plus `context-compaction-
  exhausted`: one turn's results alone don't fit, so it ends with `context-length`.
- **OpenAI:** a stand-in reply sequence with a `context_length_exceeded` 400, then success after the resend. Failure
  fixtures are captured without a real credential (openai-runner spec), as the others are.

## Risks / Trade-offs

- [A stub loses what the model read, and it may act on a wrong memory of it] → the stub says what was removed and how
  to get it back. This is the cost the opt-in accepts, and the `context` event records it.
- [OpenAI's encrypted reasoning items grow with the run and can't be stubbed] → they're usually far smaller than tool
  output. If they alone fill the window, the run fails with `context-length`, which is the safe outcome. Dropping old
  reasoning items is a possible follow-up once tested against the API's pairing rules.
- [The byte-to-token estimate is wrong for a model] → calibration from the last reported count corrects it after the
  first request, and the refusal path still catches what the estimate misses.
- [Claude Code's compaction records change between versions] → the capture tool records the version, and the
  mapping fails safe: an unrecognised record stays a debug log, and a run that can't compact still ends with
  `context-length`.
- [`TROUPE_POLICY_COMPACTION=none` stops actors that worked yesterday] → that is its purpose. The refusal names the
  fix.
- [Required `run/start` field breaks out-of-tree runners] → none exist, and version 0 promises no compatibility.

## Migration Plan

One pull request: schemas and packaged copies, SDK, core (policy, perform, runner host, recording), the three runners
and the scripted runner, fixtures, docs and tests. Existing actors have no `onContextFull`, so they keep failing, as
today. Recorded runs are unchanged. A run's start recorded before this has no `onContextFull`, and there are no such
theatres to migrate (pre-1.0: no compat leniency). Rollback is reverting the PR.

## Open Questions

None. The owner decided Q1 (D1, D2), Q2 (D4, D5) and Q3 (D8, D9) on 2026-11-12, and left the SDK's ownership of
the shared compaction code (D7) to this design.
