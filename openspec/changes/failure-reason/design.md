# Design: a failed result says why

## Context

See proposal.md for why. What's there today:

- `protocol/schemas/runner/run-event.schema.json` `$defs/result` has `status` (`ok`/`error`) and a free-text `message`.
  `run-ended.schema.json`'s `outcome.result` refers to the same `$defs/result`, so it is also the shape troupe records.
  `$defs/retry` already has a closed `reason` list: `authentication`, `rate-limit`, `network`, `server`, `other`.
- There are no theatres with recorded runs to keep reading: troupe is pre-1.0, and nothing is made optional for
  records from before a change (owner, 2026-11-07).
- The outcome is derived in one pure function, `troupe.core.runners.outcome.derive_outcome`. `run.error-result`'s
  details are `{message}`, and its fix is always "Check the run's transcript".
- What each runner ends a run for today was inventoried (task 1.1 re-checks it against the code). Every runner builds
  its result itself; the SDK has no builder.
- Contract version 0 is the draft and changes in place with no compatibility promise (`contributing/runners.md`), and
  every runner that speaks it lives in this repository.

## Goals / Non-Goals

**Goals:** a reason troupe can switch on, the same for every runner; each runner choosing it from its engine's
structured fields (or, where it gives none, the fixed words it documents), never guessed from free text; one rule for a result wherever it appears.

**Non-Goals:** acting on a reason (retry, escalate, gate); deciding #279 (whether a run fails, warns or compacts when
content is lost or cut); a reason for runs that end with no `result` (crash, timeout, cancel without a result), whose
outcome already says why; per-runner sub-codes.

## Decisions

### D1. `reason` on `result`, required exactly when `status` is `error`

One field, `reason`, beside `status`. `$defs/result` itself carries both rules: `if status error then required
reason`, and `if status ok then not required reason`. So the same rule holds wherever a result appears: what a runner
sends (`$defs/event`), what troupe passes on (`$defs/hostEvent`), and what it records (`run-ended`'s
`outcome.result`). There is no lenient form for older records, since there are none to read.

Alternatives: replacing `status` with a richer enum (`ok`, `error:quota`, ...) breaks every reader of `status` for no
gain; a separate `failure` object (`{reason, retryable, ...}`) adds fields nobody acts on yet. A required-for-`error`
field is the smallest change that troupe can switch on.

### D2. The list

| Reason | Means | Typical fix |
|---|---|---|
| `authentication` | the engine or service refused the credential | check the credential the runtime names |
| `quota` | the account is out of quota, credit or billing | add credit, or use another account |
| `rate-limit` | rate limited past what the runner will wait or retry | wait, or lower the load |
| `network` | the engine couldn't be reached, past the retries | check the connection and the endpoint |
| `server` | the engine or service kept failing on its side | try again later |
| `configuration` | the endpoint or model can't serve the run (nothing there, a redirect, no such model) | fix the runtime's endpoint or model |
| `context-length` | the conversation outgrew the model's context | a smaller task, or a longer context |
| `output-limit` | an answer was cut at the output limit, and the runner ended the run for it | raise the output limit, or a smaller task |
| `refused` | the model refused, or the service's content filter stopped it | change the direction |
| `turn-limit` | the runner's or engine's turn limit was reached | raise the turn limit in the runner's options |
| `budget` | the runner's or engine's token or cost budget was spent | raise the budget in the runner's options |
| `cancelled` | the run was cancelled and the runner still sent a result | none: it was asked to stop |
| `engine` | the engine failed in a way of its own, or sent what the runner can't act on | check the transcript; report it to the engine |
| `runner` | the runner itself failed unexpectedly | check standard error; report it to the runner |
| `other` | none of the above; the message says what | check the transcript |

The four shared with `retry` mean the same thing, so a run whose retries run out ends with its last retry's reason
(spec: runner-protocol). `configuration` is separate from `other` because it has a fix a person can act on that
differs from every other's. `engine` and `runner` are separate because they point at different things to report.
`output-limit` and `context-length` only name what a runner already ends a run for; whether it should is #279's.

The reason's meanings live in the schema's descriptions (the one named place), and `contributing/runners.md` renders
the table above from it in prose.

### D3. A failure the list doesn't name is `other`; no extension point

`reason` is a closed enum with no `$dynamicRef`. A reason only helps if troupe can act on it the same way for every
runner; a runner-specific code (`openai.invalid_prompt`) would bring back the parsing this change removes. The runner's
message still carries the specifics. A runner that keeps meeting a failure it maps to `other` files an issue to add
it, which is a contract change like this one.

Alternatives: runner-published reasons through the extension point (as `runnerErrors`) — rejected as above; an
optional `detail` code alongside — nothing would read it yet, so it waits until something does.

### D4. The outcome carries the reason, with a fix for it

`run.error-result`'s details schema gains a required `reason` (the same enum, by `$ref`). `derive_outcome` passes the
result's reason through and takes the fix from one table, `troupe.core.runners.outcome`'s per-reason fixes, which has
an entry for every member of the SDK's `FailureReason` (a test fails when one is missing). The problem names the
reason in words ("The run reached its turn limit: …"), followed by the runner's message.

The code stays `run.error-result` for every reason, including `authentication`. The existing `run.authentication`
remains troupe's own stop on an authentication *retry*; folding the two together is a decision about acting on
reasons, which is out of scope.

Every surface gets the reason only through the outcome's error, so `perform`, `status` and `logs` need no change of
their own beyond what they already render. The CLI's line for a `result` event (`render.py`) adds the reason
(`error (budget): …`) so `logs` shows it where the event is.

### D5. The SDK

`troupe_plugin_sdk.runner` gains `FailureReason = Literal[...]` (the fifteen values) and `ResultEvent.reason:
FailureReason | None = json_field("reason", default=None)`, `None` exactly for an `ok` result. `__post_init__`
refuses an `error` result without a reason and an `ok` result with one, so neither can be built, sent or parsed,
whoever is doing it. The drift test (`test_runner_types_drift.py`) already compares
fields and requiredness against the schema; it is extended to compare `FailureReason` with the schema's enum. A
runner that forgets the reason is caught by its own harness, which validates every message it sends against
`message.schema.json#/$defs/fromRunner`, and at run time by the host, which refuses the event as a protocol
violation.

The SDK is released at its own version; this is a breaking change to it (a runner built on the old SDK sends results
the new contract refuses), marked `!` in its commit.

### D6. Each runner's mapping lives in one table in that runner

- **OpenAI** (`exchange.classify` and `loop.py` already sort failures; each branch names its reason):
  401/403 `authentication`; 429 `insufficient_quota` `quota`; 429 `Retry-After` over the cap `rate-limit`;
  400 `context_length_exceeded` `context-length`; redirect, 404 without OpenAI's shape, `model_not_found`
  `configuration`; other 4xx `other`; a failed response with a code not named as the service's `other`; refusal and
  `content_filter` `refused`; `max_output_tokens` `output-limit`; other incomplete reasons and unknown statuses
  `other`; tool call without `call_id` `engine`; turn limit `turn-limit`; token budget `budget`; retries run out
  the last retry's reason; the runner's own exception `runner`. `invalid_prompt` stays `other`: OpenAI uses it for
  more than policy refusals, and refusing to guess beats a wrong `refused`.
- **Ollama:** 400 whose message says the request exceeds the available context size `context-length` (and only then
  does the message name the window: today every 400 gets the window text appended, which misleads for a 400 about
  something else); other 400 `other`; 401/403 `authentication`; 404 `configuration`; other non-retried status
  `other`; retries run out the last retry's reason (`network` or `server`); a stream's `error` record `engine`; turn
  limit `turn-limit`; the runner's own exception `runner`. A cut answer stays a `log` (#277's choice, #279's
  question).
- **Claude Code:** by subtype when it isn't `success` (`error_max_turns` `turn-limit`, `error_max_budget_usd`
  `budget`, `error_during_execution` `engine`, others `other`). For `is_error` under `success`: the last assistant
  record's `error` code when it's specific (`authentication_failed`, `billing_error`, `rate_limit`,
  `max_output_tokens`), else the last `retry`'s reason, else `api_error_status` as `_retry` maps a status when
  `terminal_reason` is `api_error`, else `other`. The last-retry step comes before the generic codes because the
  recorded `network-retries` fixture shows Claude Code calling a refused connection `server_error` with no status.
  The mapper already sees assistant records and retries in order, so it keeps the last `error` code and last retry
  reason as state, and clears both on an assistant record without an error: that call succeeded, so what came
  before it recovered and can't explain a later failure (found by the review of #314). `billing_error` and `max_output_tokens` are taken from Claude Code's documented assistant-message
  error codes; no fixture has them yet, so their tests use hand-made records shaped like the recorded ones.
- **Scripted:** a script's `result` step names `reason` (its options schema refers to the contract's enum and
  requires it for `error`, so a bad script is refused at `run/start`); `honour-with-result` cancel `cancelled`; the
  runner's own check failures `other`.

### D7. Released as a breaking protocol change

Commits touching `protocol/` and the SDK are `feat(runner-protocol)!:` / `feat(plugin-sdk)!:`, so release-please bumps
the protocol's and SDK's minor versions and the changelog says a runner's `error` result must now carry a reason.
There are no recorded theatres to migrate.

## Risks / Trade-offs

- [A runner picks the wrong reason, and a later gate acts on it] → each mapping is one table with a test per row, and
  is built from structured fields, or documented fixed words where there are none; when unsure, `other`.
- [`other` becomes a dumping ground] → the runners' tables name every failure the inventory found; `other` is left
  for genuinely unclassified ones, and D3 says how to add a reason.
- [The list grows without bound] → adding is a contract change with its own issue; every reason must come with a fix
  that differs from the others'.
- [Claude Code's undocumented fields (`terminal_reason`, `api_error_status`) change] → the order of D6 falls back to
  `other` when they're absent, and the fixtures pin today's shapes.
- [A third-party runner breaks] → none exists outside this repository; contract version 0 promises no compatibility.

## Migration Plan

One pull request: schemas, SDK, core, the four runners, fixtures and docs together, so main never has a runner the
contract refuses. Rollback is reverting it.
