# Proposal: a result says a retry wasn't safe, and a summary that hasn't ended carries no transcript

Issues: [troupe#378](https://github.com/troupe-run/troupe/issues/378) and
[troupe#313](https://github.com/troupe-run/troupe/issues/313). Both are 0.2.0 protocol changes, released together as
one breaking change. #378 is a runner contract change in the sense of decision
[#239](https://github.com/troupe-run/troupe/issues/239) (one change to the contract, its own pull request), and sits
beside [#296](https://github.com/troupe-run/troupe/issues/296)'s failure reasons. #313 follows
[#305](https://github.com/troupe-run/troupe/issues/305)'s rule.

## Why

**#378.** The LM Studio runner ([#291](https://github.com/troupe-run/troupe/issues/291), PR #379, change
`lmstudio-runner`, design D10 and D13 gap 3) retries a lost connection only while no tool call has run: the library's
`act()` starts the chat again from the direction, so a retry after a call could carry that call out twice. After a
call, it ends the run with `reason: network` and a message saying so. Nothing in the contract says a retryable
failure wasn't retried for that reason, so troupe, and any later retry policy, can't tell it from retries that ran
out, except by reading the message. And it matters to a person: the run's worktree holds what that tool call did, so
running the actor again isn't a clean retry.

**#313.** The client protocol's run schema describes a summary's `transcript` and `stderr` as "Absent: the run hasn't
ended, or its runner never started", but nothing enforces the first half: the schema's not-ended branch forbids
`outcome`, `endedAt` and `audit` and nothing else, and `RunSummary._check` doesn't check either. troupe never writes
one (the projection takes both from the run's end), so it's a gap in the contract, not in what troupe records. #305
left it out of scope and filed it.

## What Changes

- **BREAKING (runner contract): a `result` can say a failure wasn't retried because a retry wasn't safe.** A new
  field, `notRetried`, from a closed list with one entry, `side-effect`: the runner would have retried this failure,
  but something the run had already done (a tool call carried out) could happen again if it did. It is allowed only
  on an `error` result whose `reason` is one a `retry` can name (`authentication`, `rate-limit`, `network`, `server`,
  `other`), and never on an `ok` one. Absent means the runner retried until its attempts ran out, or doesn't retry
  that failure: a real absence, not a form kept for older records. The same rule holds wherever a result appears:
  what a runner sends, what troupe passes on, and what it records (design D1, D2).
- **The outcome carries it.** `run.error-result`'s details carry `notRetried` when the result did, and its fix says
  a tool call already ran, so review the run's changes (`troupe diff`) before performing again, rather than the
  reason's usual fix alone. `logs` shows it on the result's line (design D3).
- **The SDK's result type carries it**, typed as the contract's list, and refuses it on an `ok` result or beside a
  reason a retry can't name (design D4).
- **The runners that retry use it.** The LM Studio runner, the motivating case, is to send `notRetried:
  side-effect` when it ends a run on a lost connection after a tool call has run. It isn't on `main` yet, and the
  owner decided (2026-11-12) that this change merges first, so PR #379 adopts the field when it rebases onto this
  one, and #378 stays open until it does (design D5). The Ollama, OpenAI and Claude Code runners never meet the case: each retry
  sends one request again, whose conversation already holds every tool result, and calls are carried out only after
  a whole reply has arrived. So they never send it, and their docs say why (design D6). The scripted runner lets a
  script name it, so tests can drive it.
- **BREAKING (client protocol): a run summary that hasn't ended carries no `transcript` or `stderr`** (#313). The run
  schema's not-ended branch forbids both, and `RunSummary._check` refuses them, naming the field. `transcriptFormat`
  follows `transcript`. The property test's generator draws them only for an ended summary.
- **The same gap in `error` and `recording`, included** (design D7). Both are described as absent until the run
  ends, both come only from the run's end in the projection, and neither is enforced. Following #305's search-and-
  include, the not-ended branch forbids them too. This widens #313's literal scope, with the owner's agreement (2026-11-11).

Out: retrying runs from troupe's side (#378's out of scope); the LM Studio runner's use of the field, which PR #379
adopts (owner, 2026-11-12); acting on `notRetried` beyond the outcome's fix (a later
retry policy); changing what `transcript`, `stderr`, `error` or `recording` mean, or when troupe records them.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runner-protocol`: the `result` event's `notRetried`, its one value, which results may carry it, and recorded
  results held to the same rule.
- `actor-runners`: `run.error-result` carries `notRetried`, with a fix that says a tool call already ran.
- `plugin-sdk`: the SDK's result event carries `notRetried` and refuses it where the contract does.
- `scripted-runner`: a script's `error` result can name `notRetried`.
- `client-protocol`: a run summary that hasn't ended carries no `transcript`, `transcriptFormat`, `stderr`, `error`
  or `recording`.

The LM Studio runner's spec (`lm-studio-runner`) arrives with PR #379, which adds its requirement for this case
when it adopts the field (design D5).

## Impact

- **Protocol:** `protocol/schemas/runner/run-event.schema.json` (`$defs/result`, a new `$defs/notRetried`),
  `protocol/schemas/error.schema.json` (`run.error-result`'s details), `protocol/schemas/client/run.schema.json` (the
  not-ended branch), and troupe's packaged copies under `packages/troupe/src/troupe/protocol/`. Released as a breaking
  protocol change, which before 1.0 bumps the minor version.
- **SDK:** `troupe_plugin_sdk.runner`'s `ResultEvent` and a `NotRetried` type; the drift test. Breaking for the SDK
  (released at its own version).
- **Core:** `troupe.core.runners.outcome` (details and fix), `troupe.core.client.messages.RunSummary._check`, the
  CLI's line for a result event (`troupe.cli.render`).
- **Runners:** `plugins/runner-scripted` (options schema, runner); docs only for Ollama, OpenAI and Claude Code.
- **Tests:** `test_runner_schemas.py`, `test_run_outcome.py`, `test_client_schemas.py`, `test_client_messages.py`'s
  generator, the SDK's tests, the scripted runner's tests.
- **Docs:** `contributing/runners.md` (the result event, the outcomes, each runner's retry section), the generated
  event reference, and the client protocol's docs where they describe a summary.
- **No spec is added or removed and no Purpose changes,** so infrastructure's `oob/troupe-spec-purposes.json` needs no
  update.
- **Coordination:** the track-b-11-291 session (LM Studio runner, PR #379) agreed the field's name and shape, and
  said where its runner sets it (2026-11-11).
