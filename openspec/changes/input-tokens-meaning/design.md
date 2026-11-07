# Design

## Context

See proposal.md, Why. What each shipped runner does today, read from its code and fixtures:

| Runner | Engine's input count | What it reports as `inputTokens` | Cache counters |
|---|---|---|---|
| Claude Code (`mapping.py`) | Anthropic's `input_tokens`, which leaves out cache reads and writes (the `success-with-tools` fixture: 6 beside 42158 read and 5737 written) | the count, unchanged | `cache_read_input_tokens`, `cache_creation_input_tokens` |
| OpenAI (`loop.py`, its design D9) | `input_tokens`, which includes `cached_tokens` and `cache_write_tokens` | the count less reads, and less writes when every response reported them | reads always, as 0 for a response that didn't report them; writes only when every response reported them |
| Ollama (`conversation.py`) | `prompt_eval_count`, which leaves out what it served from its cache (`prompt_eval_cached_count`) | the count, unchanged | none yet (#282) |

The schema is the source of truth (decision #7), and troupe carries a copy of `protocol/schemas/` that has to change
with it. A releasable commit that changes `protocol/` releases the protocol; changing the copy releases `troupe` too
(`contributing/releasing.md`). The runner contract keeps its own version, 0, the draft.

## Goals / Non-Goals

**Goals:**

- One meaning for `inputTokens` that every engine seen so far can be mapped to without estimating.
- The meaning written where a runner's author looks: the schema, `contributing/runners.md`, and the SDK's `Usage`.

**Non-Goals:**

- Changing any runner's behaviour. The OpenAI runner's unreported cache reads are #304 (D6), Ollama's missing cache
  reads #282 (D3).
- Adding a total counter, or anything else to `usage`'s shape.
- What a runner's own token budget counts (the OpenAI runner's `maxTotalTokens` is its option, defined in its spec).
- How troupe shows or adds up usage: nothing in core reads the counters today.

## Decisions

### D1: `inputTokens` is the input not in a cache counter, and the three add up to the whole input

Defined against the other two counters, not against any engine's count. That is Anthropic's meaning, so Claude Code
maps straight across, and it's what the OpenAI runner and #282 already do.

- *Rejected: `inputTokens` is the whole input, cache included* (OpenAI's meaning). It would change two of three
  runners, and runs already recorded would then mean something different from new ones under the same contract.
- *Rejected: a fifth counter for the whole input.* It adds a field to say what a sum already says, and gives a runner
  two numbers that can disagree.

### D2: A missing cache counter means "not reported", and unseparated input stays in `inputTokens`

A runner leaves out a counter it can't report and never estimates one. Input the engine counted that the runner can't
split out stays in `inputTokens`, so the sum is still the engine's whole input as far as the runner can tell. This is
what the OpenAI runner does when only some responses report `cache_write_tokens`: it subtracts no writes and leaves
`cacheWriteTokens` out, because a partial sum would be wrong.

- *Rejected: an absent counter's tokens are counted nowhere.* The OpenAI runner can't take writes it never learned of
  out of `input_tokens`, so this would make its partial case impossible to report truthfully.
- *Rejected: an absent counter means zero.* It would make "the engine doesn't say" look like "the cache wasn't used".

The schema's existing "Absent: the engine doesn't report them" wording on `inputTokens` and `outputTokens` stays. The
cache counters' descriptions gain the same, worded as "the runner couldn't report them", since D2 covers a runner that
can't separate them as well as an engine that doesn't say.

D2 applies to each counter over the whole run: a runner that sums several requests reports a cache counter only when
every request reported it. Summing the requests that did would give a number that's neither the whole nor zero.

### D3: Ollama's gap is named, not fixed here

Ollama's `inputTokens` already has D1's meaning; what's missing is `cacheReadTokens`, so its counters add up to less
than the whole input. #282 is open for exactly that, scoped to the Ollama runner with its own fixture. Folding it in
would put a runner behaviour change into a descriptions-only protocol release. The Ollama README and its mapping row
in `contributing/runners.md` say the sum leaves cached tokens out until #282.

### D4: Released as a protocol fix, contract version unchanged

The schema change goes in a `fix(runner-protocol): ...` commit, so release-please lists it in `protocol/CHANGELOG.md`
and in troupe's changelog (the copy changes). It's a fix rather than a feature: it pins down what the contract left
vague, with no new field. No shape changes and no runner was relying on another meaning, so the runner contract stays
version 0 and `version.json` is left to the protocol's release pull request.

### D5: A test pins the descriptions where the vagueness was

`test_runner_schemas.py` gets one test that reads `usage` from `run-event.schema.json` and checks that `inputTokens`'
description names both cache counters and `usage`'s description says the three add up to the whole input. That's the
regression check sized to the bug: the defect was a description. Claude Code's mapping is already pinned by its
fixtures (6 beside 42158 and 5737), and OpenAI's whole-run cases by `test_usage_is_summed_with_cached_input_counted_apart`
and `test_tokens_written_to_the_cache_are_counted_apart_too`. Neither partial case has a test today; #304 adds both.

### D6: The OpenAI runner's unreported cache reads are named, and fixed in #304

`_Spend.add` takes a response without `cached_tokens` as 0 read, so a service that never says reports
`cacheReadTokens` 0: D2's rejected "absent means zero". OpenAI and local Ollama report `cached_tokens` on every
response (every fixture shows it), so no run seen so far is affected. Fixing it changes the runner's behaviour and its
spec, so the owner chose a separate issue, #304 (2026-11-07), keeping this change to the contract's wording as #293
asks. This change's docs don't describe the runner's current reads behaviour as conforming; #304 brings the runner's
README and mapping row into line when it lands.

## Risks / Trade-offs

- [A third-party runner already reports OpenAI's meaning] → None is known: runners are in this repository until 1.0,
  and the contract is a draft. The protocol changelog entry says what changed.
- [A description test that checks words can pass while the meaning drifts] → It checks the counter names and the
  "add up" statement, the two things the vague version lacked; the spec scenarios carry the meaning itself.
- [Ollama runs report a sum short of the whole input until #282 merges] → Named in its README and mapping row, and #282
  is on the 0.2.0 milestone with this issue.
- [An OpenAI-style service that omits `cached_tokens` gets `cacheReadTokens` 0 until #304 merges] → None seen so far;
  #304 is on 0.2.0.

## Migration Plan

None. Recorded runs from all three runners already carry this meaning, so nothing is rewritten and no reader changes.
