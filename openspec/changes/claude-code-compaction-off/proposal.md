# Proposal: Claude Code's automatic compaction off by default

## Why

Decision [#279](https://github.com/troupe-run/troupe/issues/279) (owner, 2026-11-07), point 3: Claude Code's automatic
compaction counts as losing content. A compacted run carries on from a summary of its earlier turns, and today troupe
can't tell. The default for every runner is to fail rather than lose content quietly. The Ollama runner (#277) and the
OpenAI runner already end such a run with an `error` result and #296's reason `context-length`. The Claude Code runner
is the one that doesn't: by default Claude Code compacts, both ahead of a request that would fill the window and after
the API refuses one as too long. Issue [#308](https://github.com/troupe-run/troupe/issues/308).

## What Changes

- **BREAKING (behaviour):** the Claude Code runner turns off Claude Code's automatic compaction on every run, with
  `autoCompactEnabled: false` in the settings file it already writes for each run. A run whose context fills now ends
  with an `error` result instead of carrying on from a summary. A long run that gets through today by compacting fails
  until its actor opts in to compaction (#310, which this unblocks) or its task is split.
- An `error` result whose record says Claude Code hit the context limit maps to the reason `context-length`. Claude
  Code says so in `terminal_reason`: `prompt_too_long` when the API refused the request as too long, `blocking_limit`
  when Claude Code stopped before sending a request that would not fit. Today both map to `other`.
- Two new fixtures, captured offline against a local stand-in for the API, as the other failure fixtures are: one for
  each `terminal_reason`. The capture tool checks that Claude Code sent no compaction request, so the claim that
  compaction stays off under `-p` is checked again on every recapture.
- The runner's README, the Claude Code mapping in `contributing/runners.md` and the user docs say that compaction is
  off, what a run whose context fills does, and that #310 adds the opt-in.

Out of scope (#310): letting an actor opt in to compaction, and reporting compaction through #307's `context` event.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `claude-code-runner`: a new requirement that every run has automatic compaction off, through the runner's settings
  file; a new requirement mapping the context-limit `terminal_reason` values to `context-length`; the API-error
  reason requirement says it applies only when that one doesn't; the fixtures requirement covers the context limit.

## Impact

- `plugins/runner-claude-code`: `command.py` (the settings file), `mapping.py` (the reason table), the capture tool,
  two new fixtures, tests, README.
- `contributing/runners.md` (the Claude Code mapping row for `result`), `docs/opening-night/first-performance.md` and
  `docs/stagecraft/bring-your-own-agent.md` (what a Claude Code run does).
- No contract change: `context-length` is already one of #296's reasons, in the schema, the SDK and troupe's fix text.
- Actors whose runs are long enough to compact today: they fail with `context-length` until #310.
