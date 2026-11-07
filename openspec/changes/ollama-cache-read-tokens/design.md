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
- **troupe#293's meaning** (merged as PR #312 on 2026-11-07, archived as `input-tokens-meaning`): `inputTokens`
  excludes `cacheReadTokens` and `cacheWriteTokens`, and the three add up to the whole input (runner-protocol, "Usage's
  input counters add up to the whole input"). A runner leaves out a cache counter it can't report, and input it can't
  separate stays in `inputTokens` ("A cache counter left out was not reported"). `contributing/runners.md` adds that
  a run summing several requests reports a cache counter only if every request reported it. The Claude Code runner
  gets the split from Anthropic. The OpenAI runner subtracts to match it (its design D9), and clamps a cache read to the
  input it's part of.
- **What #312 says about Ollama is wrong**: it carried over the README's claim that `prompt_eval_count` leaves out the
  cached tokens, into the README and `contributing/runners.md`'s Ollama row. The check above shows it includes them.
  This change corrects both.
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
- The contract text (troupe#293, merged).
- Re-capturing the fixtures.

## Decisions

### D1. `inputTokens` is the prompt count less the cached count, per answer

For each answer, the input is `prompt_eval_count - cached` and the cache read is `cached`, where `cached` is
`min(prompt_eval_cached_count, prompt_eval_count)`. The run sums each across its answers.

Cutting each answer's cached count to its own prompt count, rather than the run's totals, keeps each answer
self-consistent. It matters when one answer's cached count is clamped. The OpenAI runner sums
first and subtracts once, which gives the same result there because it only counts a cache read alongside its input.
Here a per-answer subtraction is the plain way to say the same thing.

*Alternative:* keep `inputTokens` as the prompt count and only add `cacheReadTokens`. Rejected: it's the meaning
troupe#293 rules out, and it would make the total input `inputTokens + cacheReadTokens` count the cached tokens twice.

### D2. A cached count counts only beside a prompt count, and never more than it

The cached tokens are part of the prompt count. An answer whose prompt count is absent or malformed gives nothing to
subtract from, and nothing to check the cached count against. So its cached count is dropped too, and the answer adds
to neither `inputTokens` nor `cacheReadTokens`. It also hasn't reported a usable cached count, so under D5 the run
reports no `cacheReadTokens`. A cached count larger than its prompt count is clamped to it, so
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

An answer that reports a prompt count and no cached count (an older Ollama, say) hasn't reported its cache reads, so
D5 applies: the run subtracts nothing and leaves `cacheReadTokens` out.

### D4. The fixtures' expected events are corrected by hand, and their provenance says so

The recorded exchanges don't change, only what the runner makes of them. So each affected `events.json` has its
`result` usage edited to the new values, and each affected `provenance.json`'s `events` note records that the result's
usage was updated for troupe#282 on the day it's done. The values come from the recorded `done` lines, worked by hand
and listed in tasks.md, and the replay test checks the runner agrees.

*Alternative:* re-capture against the local Ollama. Rejected: a new capture changes every transcript and every event
for a change that only touches the result, and the reviewer then has to re-review all of it.

### D5. Cache reads are reported only when every answer reported them

Added on rebasing onto #312's merged contract. `cacheReadTokens` is reported, and subtracted from the prompt counts,
only when every answer the run counted reported a usable cached count beside its prompt count. Otherwise the result
carries the sum of the prompt counts as `inputTokens` and no `cacheReadTokens`. That's the contract's rule: a cache
counter is reported only if every request reported it, and input that can't be separated into a cache counter stays
in `inputTokens`. Ollama 0.40.14 sends `prompt_eval_cached_count` on every answer, 0 included (the live run's first
answer did), so real runs report cache reads. The rule only bites on an Ollama that leaves the field out, or on a
malformed count.

The runner keeps the two sums (prompt counts, and cached counts each cut to their prompt count) and whether every
answer had both. It decides between them when it builds the result.

*Alternative:* the first plan, counting a missing cached count as 0 and still reporting the other answers' cache reads.
It kept each answer consistent, but it guesses that a missing count means 0, which the contract rules out: an absent
counter means it wasn't reported.

## Risks / Trade-offs

- **[`inputTokens` falls for the same Ollama run]** → It's the intended correction, and nothing in troupe reads
  `usage` to decide anything yet. The proposal says so, and the README states the meaning.
- **[A future Ollama changes what `prompt_eval_count` covers]** → The fixtures carry their Ollama version, and the
  opt-in live test runs a real model. D2's clamp keeps `inputTokens` non-negative whatever Ollama sends.
- **[#312's wrong statement about Ollama is on main until this merges]** → This change corrects the README and
  `contributing/runners.md`'s Ollama row. The PR says so, so the owner can see the two disagree.
