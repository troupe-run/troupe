# Design: Ollama's cached prompt tokens

## Context

See proposal.md for why. What the design builds on:

- **The runner today** (`conversation.py`): when an answer's `done` line comes, `_gather` reads `prompt_eval_count`
  and `eval_count` through `_count`, which takes a non-negative integer that isn't a bool, and reads anything else as
  "not reported". `_after` adds each into a run total that starts as `None`, and `_result` leaves out a counter that
  is still `None`. That's the existing rule for a counter no answer reported, and the spec's.
- **What Ollama 0.40.14 reports**: `prompt_eval_count` is the whole prompt, and `prompt_eval_cached_count` is the part
  of it taken from the cache. Checked on 2026-11-07 against the local server with `qwen3:0.6b`: the same prompt twice
  gave 78 with 0 cached, then 78 with 77 cached, and the evaluation time fell from 52 ms to 17 ms. Every captured
  fixture agrees: each second request's count includes the first request's whole prompt, and the cached part matches
  the prefix it shares with the first.
- **troupe#293's meaning** (open, a descriptions-only protocol change): `inputTokens` excludes `cacheReadTokens` and
  `cacheWriteTokens`, and the total input is their sum. The Claude Code runner gets that split from Anthropic. The
  OpenAI runner subtracts to match it (its design D9), and clamps a cache read to the input it's part of.
- **The fixtures**: five of the seven captured fixtures have answers with counts. Their recorded `done` lines already
  carry `prompt_eval_cached_count`. Their `events.json` holds the events the runner sends for that exchange, and the
  replay test checks the runner sends exactly those.

## Goals / Non-Goals

**Goals:**
- Ollama's runs report the four counters with the same meaning as the other runners'.
- Every shape a `done` line's counts can take (absent, malformed, larger than it should be) maps to one defined,
  tested outcome.

**Non-Goals:**
- Changing how a malformed counter is handled. It stays "not reported", as it is for the two counters today (see
  D3).
- The contract text (troupe#293).
- Re-capturing the fixtures.

## Decisions

### D1. `inputTokens` is the prompt count less the cached count, per answer

For each answer, the input is `prompt_eval_count - cached` and the cache read is `cached`, where `cached` is
`min(prompt_eval_cached_count, prompt_eval_count)`. The run sums each across its answers.

Subtracting per answer rather than from the run's totals keeps each answer self-consistent. It matters when one answer
reports a cached count and another doesn't, or when one answer's cached count is clamped. The OpenAI runner sums
first and subtracts once, which gives the same result there because it only counts a cache read alongside its input.
Here a per-answer subtraction is the plain way to say the same thing.

*Alternative:* keep `inputTokens` as the prompt count and only add `cacheReadTokens`. Rejected: it's the meaning
troupe#293 rules out, and it would make the total input `inputTokens + cacheReadTokens` count the cached tokens twice.

### D2. A cached count counts only beside a prompt count, and never more than it

The cached tokens are part of the prompt count. An answer whose prompt count is absent or malformed gives nothing to
subtract from, and nothing to check the cached count against. So its cached count is dropped too, and the answer adds
to neither `inputTokens` nor `cacheReadTokens`. A cached count larger than its prompt count is clamped to it, so
`inputTokens` is never negative. That's the OpenAI runner's `min(read, given)`. Ollama hasn't been seen to send
either shape. They're defined so that the property test's arbitrary lines have one expected outcome.

*Alternative:* count a lone cached count into `cacheReadTokens` anyway. Rejected: the run would report cache reads
for prompts whose size it doesn't know, and `inputTokens + cacheReadTokens` would mean a different thing from one
answer to the next.

### D3. A malformed cached count is "not reported", like the other counters

`prompt_eval_cached_count` goes through the same `_count` as the other two. A string, a negative number, a float or a
bool reads as not reported, so the answer's whole prompt count is input. Treating it as an error would end a run that
did its work over a counter troupe only reports, and would treat it differently from `prompt_eval_count`, which
already falls through this way. Ollama's counters aren't an input that selects behaviour: a bad one changes nothing
but the numbers reported. Whether a bad counter should be a `log` warning is a question for every counter at once,
not this change.

An answer that reports a prompt count and no cached count (an older Ollama, or a request that hit no cache and left
the field out) counts as 0 cached. A run where no answer reported a cached count leaves `cacheReadTokens` out, which
is the issue's "left out when no answer reported it".

### D4. The fixtures' expected events are corrected by hand, and their provenance says so

The recorded exchanges don't change, only what the runner makes of them. So each affected `events.json` has its
`result` usage edited to the new values, and each affected `provenance.json`'s `events` note records that the result's
usage was updated for troupe#282 on the day it's done. The values come from the recorded `done` lines, worked by hand
and listed in tasks.md, and the replay test checks the runner agrees.

*Alternative:* re-capture against the local Ollama. Rejected: a new capture changes every transcript and every event
for a change that only touches the result, and the reviewer then has to re-review all of it.

## Risks / Trade-offs

- **[`inputTokens` falls for the same Ollama run]** → It's the intended correction, and nothing in troupe reads
  `usage` to decide anything yet. The proposal says so, and the README states the meaning.
- **[A future Ollama changes what `prompt_eval_count` covers]** → The fixtures carry their Ollama version, and the
  opt-in live test runs a real model. D2's clamp keeps `inputTokens` non-negative whatever Ollama sends.
- **[troupe#293 words the meaning differently when it lands]** → This change follows the issue's stated meaning,
  which the other two runners already follow. If #293 changes the meaning, all three runners change together.
