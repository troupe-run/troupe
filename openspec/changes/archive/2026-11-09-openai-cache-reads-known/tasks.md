# Tasks

## 1. Tests first, against the old behaviour

- [x] 1.1 In `plugins/runner-openai/tests/fake_endpoint.py`, let `usage()` take `cached: int | None = 0`, where
  `None` leaves `cached_tokens` out of `input_tokens_details` (D6). Verify: every existing caller still passes it an
  int or nothing, and `uv run pytest plugins/runner-openai` passes unchanged on the old code.
- [x] 1.2 In `plugins/runner-openai/tests/test_openai_loop.py`, beside
  `test_usage_is_summed_with_cached_input_counted_apart`, add one test per new scenario of the openai-runner
  requirement "Usage is summed into the result", each named for what its body checks: cache writes reported by only
  one of two responses; cached tokens reported by only one of two; writes reported but cached tokens not; a cached
  count that isn't a whole number of tokens (`-1` and `"40"`, parametrised); and no input token details at all (usage
  built by hand). Each asserts the whole `result["usage"]` dict, so a counter that should be absent is checked absent.
  Verify: run them on the old code and record the outcome: the writes-by-one test passes (behaviour that must stay
  the same), and the other four fail with `cacheReadTokens` 0 (D6). Done: on the old code 5 failed and 3 passed
  (the two existing usage tests and writes-by-one); cached-by-one got `cacheReadTokens` 40 (one response's reads
  reported as the run's), the other four cases 0. Task 1.1's helper change: the whole runner-openai suite passed on
  the old code, 266 passed.

## 2. The runner reports reads only when every response reports them

- [x] 2.1 In `plugins/runner-openai/src/troupe_runner_openai/loop.py`, give `_Spend` a `reads_known` flag beside
  `writes_known` (D1): `add` clears it when a response's `cached_tokens` isn't a readable count (D2) and, with the
  other flags, when a response's usage can't be read; `usage()` subtracts reads from `inputTokens` and sets
  `cache_read_tokens` only while it holds (D3), and its docstring says both cache counters are reported only when
  every response reported them. Verify: the tests from 1.2 all pass, along with
  `test_usage_is_summed_with_cached_input_counted_apart` and `test_tokens_written_to_the_cache_are_counted_apart_too`.
- [x] 2.2 Check recorded runs replay unchanged and the budget is untouched (D5). Verify: `test_openai_fixtures.py`
  passes with no fixture's `expected.json` edited, and the `maxTotalTokens` tests in `test_openai_loop.py` pass
  unchanged.
- [x] 2.3 Update the runner's own docs: `plugins/runner-openai/README.md`'s usage paragraph says `cacheReadTokens` is
  `cached_tokens` when every response reports it, as `cacheWriteTokens` is `cache_write_tokens`, and that
  `inputTokens` is the input less whichever of them is reported; the Responses API mapping table's `usage` row in
  `contributing/runners.md` says cache reads and writes are each counted apart from input where every response
  reports them. Verify: `test_openai_readme.py` passes, the README's wording matches the spec requirement, and
  `grep -n "cacheReadTokens\|cached_tokens" plugins/runner-openai/README.md contributing/runners.md` shows no wording
  left that says reads are always reported.
- [x] 2.4 Run the full check. Verify: `uv run scripts/check.py` passes (ruff, mypy --strict, the whole test suite),
  and `openspec validate openai-cache-reads-known --strict` passes.

## Workflow follow-up

- Open the pull request as a draft (`Closes #304`), citing #293; mark it ready only after #293 has merged and this
  branch is rebased onto it, re-reading the README and `runners.md` wording against #293's as merged (D4).
- Archive the change on the branch before merging; the owner merges.
- After the merge: comment on #304 with the PR and the archived change, check it's closed and its card is Done.
