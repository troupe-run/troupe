# Design: Claude Code's automatic compaction off by default

## Context

See proposal.md for why. The runner already writes a settings file for each run, outside the workspace, and passes it
with `--settings` (`command.py`, `build()`). That file holds the permission rules translated from the effects and
`sandbox.autoAllowBashIfSandboxed: false`. It also sets `DISABLE_AUTOUPDATER` and
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` in Claude Code's environment (`ENGINE_ENVIRONMENT`). By default it loads no
setting sources; `settingSources` can load `user`, `project` or `local`.

The failure-reason mapping (`mapping.py`, `_failure_reason`) maps an `is_error` result under subtype `success` by the
last assistant record's error code, then the last retry, then `api_error_status` when `terminal_reason` is
`api_error`, else `other`. `context-length` is already one of #296's reasons, in the schema, the SDK and troupe's
fix text. Only the runner's mapping is missing.

### What the probe found

The issue asked for a live check that compaction stays off under `-p`, and for the shape of a context-limit failure.
Both were probed on 2026-11-12 with real Claude Code 2.1.319, under `-p` with the runner's flags, against a local
stand-in for the Messages API with a deliberately invalid key, so nothing reached Anthropic. The stand-in answered the
first request with a `Read` tool call and a reported `input_tokens` near the model's window, logged every later
request, and refused any other request with the API's 400 `invalid_request_error` "prompt is too long". Init reported
`claude-haiku-5-5` with a `contextWindow` of 1,000,000.

| Case | Compaction on (today) | `autoCompactEnabled: false` in `--settings` | `DISABLE_AUTO_COMPACT=1` |
|---|---|---|---|
| 185,000 tokens, then the API refuses the next request | refused, then `system/status` `compacting` and a compaction request (reactive) | one refused request, then `terminal_reason` `prompt_too_long` | the same as the setting |
| 990,000 tokens, past the window's blocking limit | `system/status` `compacting` and a compaction request before the next turn (proactive) | no further request; `terminal_reason` `blocking_limit` | the same as the setting |
| 990,000 tokens, with `--setting-sources project` and a project `.claude/settings.json` holding `autoCompactEnabled: true` and `env.DISABLE_AUTO_COMPACT: "0"` | n/a | **held**: no compaction request, `blocking_limit` | **compacted**: the project's `env` replaced the variable |
| 990,000 tokens, the setting `true` in `--settings`, the variable `1` | n/a | n/a | held: the variable overrides the setting, as documented |

With compaction off, each failure is an `assistant` record from model `<synthetic>` with `error` `invalid_request`,
`is_api_error_message` true and the text `Prompt is too long`, then a `result` record with subtype `success`,
`is_error` true, `result` `Prompt is too long` and the `terminal_reason` above. `api_error_status` is 400 for
`prompt_too_long` and absent for `blocking_limit`. Claude Code exits 1.

## Goals / Non-Goals

**Goals:**
- Every Claude Code run has automatic compaction off, including one that loads setting sources.
- A run that hits the context limit ends `error` with `context-length`, from Claude Code's own fields.
- The behaviour is pinned by fixtures captured from real Claude Code, and recapturing them checks again that no
  compaction request is sent.

**Non-Goals:**
- An opt-in to compaction, mapping `system/status` `compacting` or `compact_boundary` records, and the `context`
  event: #310. With compaction off they don't appear, and until #310 they stay a first-time `debug` log as any
  unnamed subtype is.
- Manual `/compact`: there is no interactive user under `-p`, and a direction that says `/compact` is the actor's own
  instruction, not automatic loss.
- Managed (enterprise policy) settings, which rank above `--settings` and which the runner can't override. A machine
  whose policy turns compaction on is the person's policy; the runner can't detect it.

## Decisions

### D1. `autoCompactEnabled: false` in the runner's own settings file

The runner adds `"autoCompactEnabled": false` to the settings file it already writes, beside
`sandbox.autoAllowBashIfSandboxed`, on every run.

- **Over `DISABLE_AUTO_COMPACT=1`:** the probe showed a loaded setting source's `env` block replaces the variable, so a
  project the actor loads with `settingSources` could turn compaction back on. The settings file passed with
  `--settings` ranks above user, project and local settings, and held against a project that tried both routes. It is
  also where the runner already puts what it decides about Claude Code's behaviour, so the choice lives in one place.
- **Not both:** adding the variable too would give no extra protection (whatever can replace it, the setting already
  holds against) and would put one decision in two places. #310's opt-in then changes one value.
- **Over a `PreCompact` hook:** a hook is a command Claude Code runs, so the runner would ship and launch a script on
  every platform, and a blocked compaction's stream-json shape would need its own probe. Not probed, since the setting
  held in every case.

### D2. `terminal_reason` names the context limit, and it comes first

`terminal_reason` `prompt_too_long` or `blocking_limit` on an `is_error` result maps to `context-length`, checked before
the error code, the last retry and the status. A small table in `mapping.py` (`TERMINAL_REASONS`) holds it, so a value
Claude Code adds later is one entry.

- **From fields, never text:** the text "Prompt is too long" is the same for both cases and is Claude Code's wording,
  which the failure-reason design (D6) already rules out as a source.
- **First, not after the retry:** the assistant record's error code `invalid_request` is generic and not in the table,
  so it would fall through anyway. But a run that retried a rate limit and then overflowed must end `context-length`,
  not `rate-limit`: the terminal reason says why the run ended, a retry only says what happened on the way. The
  spec's scenario pins it.
- **Only under `is_error`:** a successful result with an unexpected `terminal_reason` stays `ok`.

### D3. Two fixtures, captured offline through the runner's own launch

`context-limit-refused` (185,000 tokens, the stand-in refuses the second request) and `context-limit-blocked` (990,000
tokens, no second request). The capture tool gets a second stand-in, beside `_RefuseEveryRequest`, that streams one
`Read` tool call with the given usage and refuses anything later as too long. It launches Claude Code through the
runner's `build()`, as `edit-denied-by-effects` does, so the recording is of the settings file a run really gets.

- **Repeatable check:** the stand-in counts requests. The tool refuses to write the fixture if Claude Code sent a
  compaction request (`system/status` `compacting` in the output, or more requests than the case expects). The probe
  in this design becomes a check that runs on each recapture, on whatever Claude Code version is captured.
- **Offline, as the spec requires of failure fixtures:** no credential, nothing reaches Anthropic, so an agent session
  can capture them. The stand-in's refusal uses the Anthropic API's documented error type and message.

### D4. A real-API confirmation is the owner's, and doesn't block the change

The probe ran real Claude Code under `-p`, so it shows what Claude Code does. What it can't show is the real API's own
refusal. Filling a 1,000,000-token window on `claude-haiku-5-5` costs about USD 0.50 at the rate the probe's result
reported. The tasks include an optional owner run, budget-capped, that sends a real over-long direction and checks the
result is `context-length`. It runs with the credential the live test uses, never in an agent session, and the change
doesn't wait on it.

## Risks / Trade-offs

- [A long run that compacts today fails] → This is the decision (#279). The README, the user docs and the changelog
  say so, with the way out: split the task, or opt in once #310 lands.
- [Claude Code renames the setting or the `terminal_reason` values] → The setting is documented. A renamed
  `terminal_reason` maps to `other`, which still fails the run, so nothing is lost quietly. A recapture finds a
  setting that stops working: the tool refuses to write the fixture.
- [`blocking_limit` might mean something other than the context] → In 2.1.319 it appears only with the text "Prompt is
  too long", when the conversation is past the window and compaction is off. If Claude Code reuses it, the reason
  would say `context-length` for another limit; the message still carries Claude Code's text.
- [The probe's stand-in reports usage it didn't count] → Claude Code decides from the usage the API reports, which is
  what a real response carries. D4's owner run covers the real API.

## Migration Plan

No data migration. The runner's version bump through release-please carries the behaviour change in its changelog,
with the commit marked as a behaviour change. Rollback is reverting the commit.
