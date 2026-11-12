# Design: a result says a retry wasn't safe, and a summary that hasn't ended carries no transcript

## Context

See proposal.md for why. What's there today:

- `protocol/schemas/runner/run-event.schema.json` `$defs/result` has `status`, `message` and, exactly when `status`
  is `error`, a `reason` from `$defs/failureReason` (#296). `$defs/retry`'s `reason` is a closed list of five:
  `authentication`, `rate-limit`, `network`, `server`, `other`. `run-ended.schema.json`'s `outcome.result` refers to
  the same `$defs/result`, so one rule covers what a runner sends, what troupe passes on and what it records.
- `troupe.core.runners.outcome` builds `run.error-result` from the result: details `{reason, message}` and a fix from
  `FAILURES[reason]`. `protocol/schemas/error.schema.json` describes those details with `additionalProperties: false`.
- The SDK's `ResultEvent` (`troupe_plugin_sdk.runner`) checks `reason` against `status` in `__post_init__`, and
  `test_runner_types_drift.py` compares the SDK's types with the schema.
- **Which runners retry, and how** (read from the code, 2026-11-11):
  - **Ollama** (`conversation.py` `_request`) retries one `/api/chat` request. Tool calls are carried out in
    `_call_tools` only after `_gather` has a whole answer, and every request carries the conversation with every
    tool result so far. A retry never repeats a call.
  - **OpenAI** (`loop.py`, `exchange.py`) is the same shape: `exchange` retries one Responses request inside a turn,
    and the loop carries out the reply's calls only after `exchange` returns.
  - **Claude Code** retries its own API calls (`system/api_retry`), each of which is one model request inside
    Claude Code's own loop, whose conversation holds every tool result. The runner only maps those retries.
  - **LM Studio** (PR #379, `loop.py` on branch `lmstudio-runner`, confirmed by its session): retries an
    `EngineError` whose failure is `lost` (the connection dropped) or `unreachable` (a reconnect's greeting failed),
    within 3 attempts, only while no tool call has been carried out in the run, because each retry calls `act()`
    again from the direction. After a call, it ends `network` with a message saying a retry could run a tool twice.
    A message `timeout` is never retried, before or after a call, and today wrongly gets the same sentence. The turn
    limit and the token budget close the client deliberately and end `turn-limit` and `budget`.
  - The scripted runner doesn't retry; a script sends what it's told to.
- `protocol/schemas/client/run.schema.json`'s summary: the `state` branch requires `outcome` and `endedAt` when
  ended, and forbids `outcome`, `endedAt` and `audit` otherwise. `transcript`, `stderr`, `error` and `recording` are
  each described as absent until the run ends, but nothing forbids them. The projection
  (`core/runs/projections.py` `summary`) takes all four, and `transcriptFormat`, from the recorded end only.
  `RunSummary._check` mirrors the schema. The property test in `test_client_messages.py` draws `transcript` for any
  state.

## Goals / Non-Goals

**Goals:** a field troupe can switch on that tells "not retried because a retry wasn't safe" from "retries ran out";
the same rule wherever a result appears; a fix a person can act on; a run summary whose fields agree with its state,
in the schema and in `RunSummary`.

**Non-Goals:** troupe retrying runs itself; a retry policy that reads `notRetried`; changing how any runner decides to
retry; changing what a summary's fields mean or when troupe records them.

## Decisions

### D1. `notRetried` on `result`, a closed list with one value

One optional field beside `reason`: `notRetried`, `$ref` to a new `$defs/notRetried`, `enum: ["side-effect"]`.
`side-effect`: the runner would have retried this failure, but a tool call had already been carried out, and a retry
could carry it out again.

Why a list and not a boolean: the field names *why* the runner held back, which is what a later policy would act on,
and leaves room for another cause (for example a request the service says isn't idempotent) as a contract change of
its own, the way #296's list grows. A `true`-only boolean says nothing more and can't grow. Like `reason`, the list
has no extension point: a runner can't add values.

Name: `notRetried` reads as what happened ("not retried: side-effect") and pairs with the `retry` event; agreed with
the LM Studio runner's session. Rejected: `retrySafe: false` (a negative boolean, and `true` would mean nothing);
`retry: "exhausted" | "unsafe"` on every error result (asks every runner to report exhaustion too, which `reason`
plus the last `retry` event already shows, and makes a required field out of something most failures don't have).

**What `side-effect` covers for a rejected call** (raised by the LM Studio session): that runner counts every call it
answered, including one the library rejected (an unknown tool or bad arguments) that the SDK answered with an error
and that changed nothing. So it holds back after a rejected call too. That's the safe direction, and the field
reports what the runner did. The value's description says "a tool call had already been carried out or answered",
so it stays true for that runner, and runners aren't asked to tell the two apart (owner, 2026-11-11: keep it).

### D2. Only on an `error` result whose reason a retry can name

`$defs/result` gains: `if notRetried is present then status is error and reason is one of retry's five`. Written as
`"dependentSchemas": {"notRetried": {"required": ["reason"], "properties": {"status": {"const": "error"}, "reason":
{"$ref": "#/$defs/retryReason"}}}}` (the result's existing `if`/`then`/`else` already holds the reason rule, so this
one uses `dependentSchemas` rather than a second `if`), with `$defs/retry`'s inline enum moved to a named `$defs/retryReason` that both use, so
the two can't drift. Because the rule is on `$defs/result`, it holds for `$defs/event`, `$defs/hostEvent` and
`run-ended`'s `outcome.result` alike: no lenient form for records, since there are none from before it (#305).

Absent is a real absence (the runner retried until its attempts ran out, or doesn't retry this failure), not a form
for older records, so the field isn't required anywhere.

### D3. The outcome and the surfaces

`run.error-result`'s details gain an optional `notRetried` (same `$ref`), present exactly when the result had it.
`derive_outcome` passes it through. The fix comes from one place: when `notRetried` is `side-effect`, the fix is "The
runner didn't retry, because a tool call had already run and a retry could run it again. Review the run's changes
with `troupe diff <run>`, then perform the actor again", followed by the reason's own fix from `FAILURES`. The problem
stays the reason's. A table keyed by the `notRetried` value, with a test that every value has an entry, keeps the next
value from being forgotten.

The CLI's line for a `result` event (`render.py`) adds it: `error (network, not retried: side-effect): …`. `status`
and `perform` show it through the outcome's error, as #296 did for the reason.

### D4. The SDK

`NotRetried = Literal["side-effect"]` and `RetryReason = Literal[...]` (the five, which `RetryEvent.reason` uses too),
and `ResultEvent.not_retried: NotRetried | None = json_field("notRetried", default=None)`. `__post_init__` refuses it
on an `ok` result and beside a reason outside `RetryReason`, naming `notRetried`. The drift test compares both
literals with the schema's enums. Breaking for the SDK (a host on the new SDK reads a field an old one refuses as
unknown), marked `!`.

### D5. The LM Studio runner

PR #379 is expected to merge first (its session: ready, review clean, CI running, 2026-11-11). So this branch rebases
onto `main` once it has, and then:

- `_from_error` sets `notRetried: side-effect` exactly when `error.failure` is `lost` or `unreachable` and the run has
  carried out or answered a tool call. Not for `timeout` (never retried), and not for the turn limit or the budget.
- The "a retry could run a tool twice" sentence follows the same condition, so a timeout after a call no longer
  carries it.
- `test_a_lost_connection_after_a_call_isnt_retried` asserts the field; a new test pins that a timeout after a call
  has neither the field nor the sentence.
- A delta to `lm-studio-runner`'s spec says so, and its README and `contributing/runners.md`'s LM Studio section.

If #379 hasn't merged when the rest of this change is reviewed and ready, this change ships without the LM Studio
part, the delta and tasks move to a follow-up issue on the board, and #378 stays open until it lands, since #378's
"in" names the LM Studio runner using it. The owner decides which at that point.

### D6. Ollama, OpenAI and Claude Code don't meet the case

#378 asks whether the runners that resend a whole conversation meet the same case. They don't (Context): each retry
repeats one model request, whose conversation already holds every tool result, and calls are carried out only after a
whole reply. A dropped stream that had already streamed a call's request is retried before that call runs. So they
never send `notRetried`, and no code changes. `contributing/runners.md`'s section on each one says so in a sentence,
so the next runner author sees which shape needs the field.

### D7. A summary that hasn't ended: `transcript`, `stderr`, and also `error` and `recording`

The not-ended branch of the summary schema becomes `{"properties": {"outcome": false, "endedAt": false, "audit":
false, "transcript": false, "transcriptFormat": false, "stderr": false, "error": false, "recording": false}}`.
`RunSummary._check` refuses each, naming the field. `transcriptFormat` already follows `transcript`
(`dependentRequired`); it's listed so the message names it either way.

`error` and `recording` go beyond #313's wording. Both are described as absent until the run ends, both come only from
the end in the projection, and neither is enforced: the same gap. #305's practice was to search for the same pattern
and include what turned up; leaving them would mean a second change for the same three-line fix. The owner agreed
(2026-11-11).

The property test's generator draws `transcript`, `transcriptFormat`, `stderr`, `error` and `recording` only for an
ended summary, and a property test checks that the schema and `RunSummary` agree on every drawn summary with one of
them added to a summary that hasn't ended. `test_client_schemas.py`'s "running run" fixture is checked for any of the
five.

### D8. Released as one breaking protocol change

Commits touching `protocol/` are `feat(runner-protocol)!:` and `feat(protocol)!:`, and the SDK's
`feat(plugin-sdk)!:`. Every commit is signed and carries `Signed-off-by` (`git commit -S -s`), since the merge queue
rebuilds commits unsigned and DCO fails there without it. There are no theatres to migrate.

## Risks / Trade-offs

- [The LM Studio PR doesn't merge in time, and the motivating runner doesn't use the field] → D5's fallback, decided
  by the owner then; the field is defined either way, which #379's session asked for.
- [A runner sets `notRetried` where a retry would in fact have been safe] → it only stops troupe from retrying, the
  safe direction; the message still says what happened.
- [`run-event.schema.json` changes collide with another runner-contract change in flight] → checked open PRs at
  propose time: #309 (Ollama's cut answer) changes the Ollama runner, not the schema. Re-check before pushing.
- [A summary consumer relied on `error` on a running run] → troupe never writes one, and the client protocol is
  troupe's own; pre-1.0 with no compatibility promise.

## Migration Plan

One pull request: schemas, SDK, core, CLI, scripted runner, LM Studio runner (D5), fixtures and docs, closing #378
and #313. Rollback is reverting it.

## Resolved Questions

- D1: `side-effect` covers a call that was answered but rejected, keeping the LM Studio runner's conservative count
  (owner, 2026-11-11).
- D7: the summary rule includes `error` and `recording` (owner, 2026-11-11).
