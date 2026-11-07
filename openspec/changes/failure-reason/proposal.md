# Proposal: a failed result says why

Issue: [troupe#296](https://github.com/troupe-run/troupe/issues/296). Found building the OpenAI runner
([#162](https://github.com/troupe-run/troupe/issues/162), change `openai-style-runner`, design D12 gap 1). One of the
reasons is the question [#279](https://github.com/troupe-run/troupe/issues/279) asks second (does the contract name lost
or cut content); this change gives it a name without deciding #279.

## Why

Every failed run ends with a `result` whose `status` is `error` and whose only explanation is free text. The OpenAI
runner alone ends runs that way for a refused credential, an account out of quota, a context-length error, a refusal,
an incomplete response, a failed response, the turn limit, the token budget and retries run out, and the Claude Code
and Ollama runners have lists of their own. troupe can't tell a person "fix your key" from "raise the budget" without
parsing each runner's words, and neither could a later gate or escalation. The contract is still version 0, the
draft that changes in place, so this is the cheapest time to add it.

## What Changes

- **BREAKING (runner contract): a `result` with status `error` carries a `reason`**, from one closed list. A `result`
  with status `ok` carries none. A runner's `error` result without a reason, or with one off the list, doesn't
  validate, so the host treats it as a protocol violation, as it does any other malformed event.
- **The list** (design D2): `authentication`, `quota`, `rate-limit`, `network`, `server`, `configuration`,
  `context-length`, `output-limit`, `refused`, `turn-limit`, `budget`, `cancelled`, `engine`, `runner`, `other`. The four
  that a `retry` can also name (`authentication`, `rate-limit`, `network`, `server`) mean the same thing on both, so
  a run whose retries run out ends with the reason of its last retry.
- **A reason the list has no entry for is `other`**, and the message says what happened. A runner can't add its own
  reasons: a reason is only useful if troupe can act on it the same way for every runner. A runner that keeps
  meeting a failure `other` covers files an issue to add it to the list (design D3).
- **One rule everywhere.** troupe holds the results it records and reads back to the same rule: there are no
  theatres from before this change to keep reading, so nothing is made optional for them.
- **The outcome carries the reason.** A run whose `result` had status `error` is still `failed` with
  `run.error-result`; its details gain the `reason`, and its fix says what to do for that reason (check the
  credential, raise the budget, shorten the direction...) instead of always "check the transcript". This is how
  every surface shows it (status, logs, perform), with no surface-only behaviour.
- **Every runner troupe ships reports it:** Claude Code (from the CLI's result subtypes, its API error, and its own
  failures), Ollama (its HTTP errors, the context window #277 guards, its turn limit), OpenAI (each failure D8 of its
  change already names), and the scripted runner (a script names the reason, so tests can drive each one). The
  plugin SDK's result type takes the reason, and refuses an `error` result built without one.

Out: what troupe does with a reason (retry, escalate, route to a role), which is later; #279's decisions about what a
run does when content is lost or cut (this change only names `context-length` and `output-limit` where a runner
already ends a run for them); a reason on `ok` results or warnings (a cut answer that stays a `log` stays a `log`).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runner-protocol`: the `result` event carries a `reason` from a closed list exactly when its status is `error`; the
  list and what each reason means; recorded results held to the same rule.
- `actor-runners`: a failed result's reason reaches the outcome's `run.error-result`, with a fix for that reason, and
  every surface shows it.
- `claude-code-runner`: which reason each of its failures reports.
- `ollama-runner`: which reason each of its failures reports.
- `openai-runner`: which reason each of its failures reports.
- `scripted-runner`: a script's `error` result names its reason.
- `plugin-sdk`: the SDK's result event carries the reason.

## Impact

- **Protocol:** `protocol/schemas/runner/run-event.schema.json` (the result's `reason`, required for `error`,
  wherever a result appears), `protocol/schemas/error.schema.json` (`run.error-result`'s details), and
  troupe's packaged copy. Released as a protocol change: a breaking one, which before 1.0 bumps the minor version.
- **Core:** `troupe.core.runners.outcome` (details and the per-reason fix table), and the CLI's rendering of a
  result event.
- **SDK:** `troupe_plugin_sdk.runner`'s `ResultEvent` and a `FailureReason` type (released at the SDK's own version).
- **Runners:** `plugins/runner-claude-code`, `plugins/runner-ollama`, `plugins/runner-openai`,
  `plugins/runner-scripted`, their fixtures and tests; troupe's audition scripts.
- **Docs:** `contributing/runners.md` (the result event, the reason list, the outcomes table, each runner's mapping
  section), `protocol/README.md` if it describes the result, each runner's README, and the generated event reference.
- **No spec is added or removed and no Purpose changes,** so infrastructure's `oob/troupe-spec-purposes.json` needs no
  update.
