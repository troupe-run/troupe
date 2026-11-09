# Design: the OpenAI runner reports cache reads only when every response reports them

## Context

See proposal.md for why. `_Spend` in `plugins/runner-openai/src/troupe_runner_openai/loop.py` sums each response's
usage. For cache writes it keeps `writes_known`, cleared by any response whose `input_tokens_details` has no readable
`cache_write_tokens`; `usage()` then subtracts no writes from `inputTokens` and leaves `cacheWriteTokens` out (#162's
design D9). For cache reads it has no such flag: `read = read if _count(read) else 0`, so a missing or unreadable
`cached_tokens` counts as 0 read, and `cacheReadTokens` is always present.

#293's draft wording (the `input-tokens-meaning` change, in progress) adds two runner-protocol requirements: the input
counters add up to the whole input, and "A cache counter left out was not reported": a runner leaves out a counter it
can't report, never estimates one, and keeps input it can't separate into a cache counter in `inputTokens`. Its design
D6 names this runner's reads as the gap and leaves the fix to #304.

Every recorded fixture in `plugins/runner-openai/fixtures/responses/` reports `cached_tokens` on each completed
response (OpenAI's as 0, Ollama's as 0 and 373), and the test helper `usage()` in `tests/fake_endpoint.py` always
sets it.

## Goals / Non-Goals

**Goals:**
- Reads are treated exactly as writes already are, so the runner meets #293's "A cache counter left out was not
  reported".
- Both partial cases, and reads and writes being decided apart, have tests.

**Non-Goals:**
- Changing the contract, its schema or `contributing/runners.md`'s contract-level note: #293.
- The Ollama runner's cache reads: #282.
- What `maxTotalTokens` counts (see D5).
- Clamping a response's reads to its input tokens (`min(read, given)`): unchanged, and no recorded response reaches it.

## Decisions

### D1: A `reads_known` flag beside `writes_known`, each decided on its own

`_Spend` gets `reads_known: bool = True`. `add` clears it when a response's usage has no readable `cached_tokens`, as
it clears `writes_known` for `cache_write_tokens`, and clears it with the others when a response has no readable usage
at all. `usage()` subtracts reads only while `reads_known` holds and reports `cacheReadTokens` only then, as it already
does for writes. The two flags don't affect each other: a service that reports writes but not reads still gets its
writes counted apart, and the other way round.

- *Rejected: one `cache_known` flag for both.* It would drop OpenAI-style writes from a service that reports them just
  because it doesn't report reads, which is less than the service told us.

### D2: A cached count that can't be read counts as not reported

A `cached_tokens` that isn't a non-negative integer (a string, a negative number, a bool, `null`) clears
`reads_known`, the same test (`_count`) and outcome `cache_write_tokens` already has. There's no warning and the run
goes on.

- *Rejected: end the run, or warn, under "a malformed input is an error".* That rule is about inputs that select
  behaviour, where falling through to a default turns a mistake into wrong behaviour that looks like success. Here
  the service's count is a measurement, and the fall-through is to claiming nothing: the result says less, never
  something wrong. Ending a run that otherwise worked would lose the actor's work over a number nothing in core reads.
  A warning would be new behaviour that writes don't have; if it's wanted, it should cover both counters, in its own
  issue.
- *Rejected: keep treating it as 0.* That's the defect: 0 is a claim the service didn't make.

### D3: Reads some responses reported stay in `inputTokens`

Once `reads_known` is cleared, the reads the other responses reported aren't subtracted anywhere: they stay in
`inputTokens`, so `inputTokens` is the whole input less any writes reported. This is #293's rule (input the runner
can't separate into a cache counter stays in `inputTokens`) and what writes already do.

- *Rejected: subtract the reads that were reported, and leave `cacheReadTokens` out.* Those tokens would then be
  counted nowhere, and the three input counters wouldn't add up to the whole input.
- *Rejected: report the partial sum as `cacheReadTokens`.* It would read as the run's whole reads when it's only some
  responses': an estimate by another name.

### D4: Proposed now; the pull request follows #293's

#304 says to propose after #293 merges, since it builds on that wording. The runner's behaviour doesn't need #293's
text to land first, and #293's draft spec is settled enough to cite: its requirement "A cache counter left out was not
reported" is what this change meets. So the change is proposed and can be built now, and the pull request is opened
as a draft citing #293, and marked ready only once #293 has merged and this branch is rebased onto it. The README and
`contributing/runners.md` edits are to the OpenAI runner's own wording (its usage paragraph and its Responses API
mapping row), which #293's task 2.4 leaves for #304, so the two changes touch different lines of `runners.md`; a
conflict on rebase is resolved by keeping #293's contract note and this change's row.

If #293's wording changes before it merges, this change's spec scenarios still hold (they're this runner's behaviour,
stated without the contract's words); only the docs' phrasing is re-checked on rebase.

### D5: The token budget is unchanged

`maxTotalTokens` counts `_Spend.tokens`, the raw sum of `input_tokens` and `output_tokens` over the responses, which
neither flag touches. A service that doesn't report reads hits its budget at exactly the same point as before.

### D6: Tests drive the loop through the fake endpoint

The tests sit beside `test_usage_is_summed_with_cached_input_counted_apart` in `tests/test_openai_loop.py`, one per
new spec scenario, each running the loop over scripted replies and reading the `result` event, as the existing usage
tests do. `usage()` in `tests/fake_endpoint.py` gets `cached: int | None = 0`, where `None` leaves `cached_tokens`
out, so a test can build a response without it; the scenario with no input token details at all builds its usage by
hand. The fixture replay tests (`test_openai_fixtures.py`) show recorded runs replay unchanged, since every recorded
response reports `cached_tokens`.

Each new test is checked against the old code before the fix: the two read scenarios and the unreadable one fail on
main (they get `cacheReadTokens` 0), and the writes-only-by-one scenario passes on main, pinning behaviour that must
stay the same.

## Risks / Trade-offs

- [A service that reports `cached_tokens` on some responses only (for instance, only once its cache warms up) loses
  `cacheReadTokens` for the whole run] → That's the contract's meaning: the result reports what it knows for the
  whole run or nothing. None seen so far; OpenAI and Ollama report it on every response, 0 included.
- [#293's wording shifts before it merges] → D4: the spec scenarios don't depend on it; the docs are re-read on
  rebase.
- [Recorded runs change] → None do: every fixture reports `cached_tokens` on each response, and the fixture replay
  tests pass unchanged.

## Migration Plan

None. Results already recorded keep what they say; a run against a service that omits `cached_tokens` stops claiming
0 reads. Released as a `fix(runner-openai)` commit.
