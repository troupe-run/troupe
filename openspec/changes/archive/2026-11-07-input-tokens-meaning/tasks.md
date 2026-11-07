# Tasks

## 1. The contract says what each counter counts (design D1, D2, D4, D5)

- [x] 1.1 Write the test first: in `packages/troupe/tests/test_runner_schemas.py`, a test that reads `result.usage`
  from `run-event.schema.json` and checks that `inputTokens`' description names `cacheReadTokens` and
  `cacheWriteTokens`, that `usage`'s description says the three add up to the whole input, and that each cache
  counter's description says what its absence means. Verify: it fails on main's schema, run and shown.
- [x] 1.2 Rewrite the descriptions of `usage`, `inputTokens`, `cacheReadTokens` and `cacheWriteTokens` in
  `protocol/schemas/runner/run-event.schema.json` to say D1 and D2 (input not in a cache counter; the three add up;
  a cache counter left out wasn't reported, and input the runner couldn't separate stays in `inputTokens`), and copy
  the file to `packages/troupe/src/troupe/protocol/runner/`. No property, type or `required` changes. Verify: 1.1's
  test passes, `diff` of the two files is empty, and `git diff` shows only `description` values changed.
- [x] 1.3 Say the same in the SDK's `Usage` docstring (`packages/troupe-plugin-sdk/src/troupe_plugin_sdk/runner.py`).
  Verify: `uv run pytest packages/troupe-plugin-sdk` passes.
- [x] 1.4 `contributing/runners.md`: the `result` row of the run events table points to a new "What usage counts" note
  under it, which states D1 and D2 with the two engine shapes (an input count that leaves the cache out, as
  Anthropic's; one that includes it, as OpenAI's) and the subtraction. Verify: the row's anchor link reaches the note
  in a rendered preview (`gh markdown-preview` or GitHub's file view on the pushed branch), and every counter name in
  it matches the schema.
- [x] 1.5 Commit 1.1 to 1.4 as `fix(runner-protocol): ...` (subject ≤ 72 characters), so the protocol and troupe
  release it (D4). Verify: `uv run scripts/check.py` passes before the commit, and `git log -1 --stat` shows
  `protocol/` and the troupe copy in it.

## 2. Each shipped runner is checked against the meaning (design D3, D5, D6)

- [x] 2.1 Claude Code: add a sentence to its mapping row in `contributing/runners.md` that Anthropic's `input_tokens`
  already leaves out cache reads and writes, so it maps unchanged. Verify: cite the `success-with-tools` fixture's
  result (6 beside 42158 read and 5737 written) and `test_claude_code_mapping.py`'s case in the commit message.
- [x] 2.2 Ollama: in `plugins/runner-ollama/README.md` and its mapping row in `contributing/runners.md`, say that
  `prompt_eval_count` leaves out the prompt tokens served from the cache, so `inputTokens` has the contract's meaning,
  and that its counters add up to less than the whole input until #282 reports those as `cacheReadTokens`. Verify:
  the wording matches #282's scope, and `openspec/specs/ollama-runner/spec.md` needs no change (its requirement
  doesn't contradict D1).
- [x] 2.3 The scripted runner sends whatever `usage` its script gives, and its options schema takes that by `$ref` to
  the contract's `usage`, so the new descriptions reach a script's author with no change. Confirm the `$ref` at
  `options.schema.json`'s `usage` still resolves to `result.properties.usage`, and that no fixture or test script in
  `plugins/runner-scripted` and `packages/troupe/tests` gives a usage that contradicts D1, such as a comment or name
  calling `inputTokens` the whole input beside cache counters. Verify: the grep and
  its result in the commit message.
- [x] 2.4 OpenAI: leave its README and Responses mapping row as they are (#304 changes them with the runner). Verify:
  `test_usage_is_summed_with_cached_input_counted_apart` and `test_tokens_written_to_the_cache_are_counted_apart_too`
  pass and match the runner-protocol scenario "An engine whose input count includes the cache", cited with #304 in
  the commit message, and nothing this change writes calls the runner's handling of unreported reads conforming.
- [x] 2.5 Commit 2.1 to 2.4 as `docs(runners): ...`. Verify: `uv run scripts/check.py` passes before the commit.

## 3. Whole change

- [x] 3.1 Validate and run everything. Verify: `openspec validate input-tokens-meaning --strict` passes and
  `uv run scripts/check.py` passes on the branch's head; CI on Linux, macOS and Windows passes once the PR is ready.
  Done: validate passes; the full check passed before 53bde02 (4751 passed) and the guard's scoped check before
  c0e2aa5; CI run 42359514207 on 25873ff passed every job on Linux, macOS and Windows, Python 3.12 to 3.15.

## Workflow follow-up

- Draft PR closing #293 (`Closes #293`), act on Claude's review, mark ready, `/opsx:archive` on the branch, owner merges.
- After the merge: comment on #293 with the PR and the archived change, check it's closed and its card is Done.
- Comment on #282 and #304 that the contract now says what their `cacheReadTokens` must mean, linking the PR.
- No infrastructure `oob/troupe-spec-purposes.json` update: no Purpose changes.
