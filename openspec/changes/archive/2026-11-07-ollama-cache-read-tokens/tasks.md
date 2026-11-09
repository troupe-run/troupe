# Tasks

## 1. Count the cached prompt tokens (design D1, D2, D3)

- [x] 1.1 Before changing the runner, add the spec's "Two requests" case with no cached count to
  `test_ollama_conversation.py` if it isn't already exact (`final(...)` lines carry no `prompt_eval_cached_count`), and
  run it on the unchanged code. Verify: it passes before the change and still passes after it, so a run that never
  reports a cached count keeps `{"inputTokens": 420, "outputTokens": 65}`.
- [x] 1.2 Give `fake_ollama.done()` (and the `calls`/`final` helpers that build on it) a `cached` count, written as
  `prompt_eval_cached_count` only when given. Verify: `test_ollama_fake.py` passes, and a new case there checks a
  `done(cached=4)` line holds `"prompt_eval_cached_count": 4` and a default one holds no such key.
- [x] 1.3 Write failing tests in `test_ollama_conversation.py`, one per new spec scenario, named for what each checks:
  cached counts 88 and 1218 beside prompt counts 1222 and 1276 give `inputTokens` 1192, `cacheReadTokens` 1306,
  `outputTokens` 56; a second answer with no cached count gives `inputTokens` 400 and `cacheReadTokens` 20; a cached
  count with no prompt count gives `usage` `{"outputTokens": 7}`; cached 12 beside prompt 10 gives `inputTokens` 0
  and `cacheReadTokens` 10. Verify: each fails on the unchanged runner, for the reason its name gives.
  (Done: three failed on the unchanged runner. The no-prompt-count case passed there, because that runner ignored
  cached counts altogether. It can only fail once the runner reads them; 1.5's property catches that mutation.)
  (Changed by 5.2: a second answer with no cached count now gives `inputTokens` 420 and no `cacheReadTokens`.)
- [x] 1.4 In `conversation.py`, read `prompt_eval_cached_count` through `_count` beside the other two counters, and
  when the answer is counted add `prompt - min(cached, prompt)` to the input total and `min(cached, prompt)` to a new
  cache-read total, only when the prompt count was read. `_result` adds `cacheReadTokens` to `usage`, left out while
  its total is `None`. Verify: 1.1's and 1.3's tests pass, and so does the rest of
  `uv run pytest plugins/runner-ollama`.
- [x] 1.5 Extend `test_ollama_conversation_properties.py`'s `_LINE` with `prompt_eval_cached_count` (integers from -5
  and arbitrary JSON, as the other counters), and add a property: whatever the lines, a result's `usage` never holds
  a negative counter, and holds `cacheReadTokens` only when it holds `inputTokens`. Verify: the property test passes.
  To check it can fail, drop the `min` from 1.4 and confirm a negative `inputTokens` is found, then put it back.
  (Done: random lines alone never reached that case, so the answers' last line is now sometimes a counted one.
  Then both mutations were found: without the `min`, a negative `inputTokens`; counting a cached count with no
  prompt count, `{"cacheReadTokens": 0}`.)

## 2. Correct the fixtures (design D4)

- [x] 2.1 Edit the `result` usage in each fixture's `events.json` to the values worked from its recorded `done` lines:
  `success-with-tools`, `network-retries` and `server-retries`: `inputTokens` 1192 ((1222 − 88) + (1276 − 1218)),
  `outputTokens` 56, `cacheReadTokens` 1306; `refused-by-effects`: `inputTokens` 1187 ((1229 − 119) +
  (1302 − 1225)), `outputTokens` 72, `cacheReadTokens` 1344; `thinking`: `inputTokens` 1120 (1238 − 118),
  `outputTokens` 107, `cacheReadTokens` 118. `context-overflow` and `stream-error` have no counts and don't change.
  Keep each file's formatting as the capture tool writes it: change only the usage. Verify: `test_ollama_fixtures.py`'s
  replay test passes with these events, and fails with the old ones on the 1.4 runner.
- [x] 2.2 In those five fixtures' `provenance.json`, extend `events` to say the result's usage was updated by hand for
  troupe#282, with the date. Verify: `git diff` on the fixtures shows only the usage lines and the `events` note, and
  `uv run pytest plugins/runner-ollama` passes.

## 3. Correct the docs

- [x] 3.1 In `plugins/runner-ollama/README.md`'s run events section, replace the paragraph that says cached tokens
  "aren't in `inputTokens`": `inputTokens` is the sum of each answer's `prompt_eval_count` less its
  `prompt_eval_cached_count`, `cacheReadTokens` the sum of `prompt_eval_cached_count`, `outputTokens` the sum of
  `eval_count`, no `cacheWriteTokens` because Ollama reports none, and the total input is `inputTokens +
  cacheReadTokens`. Verify: `test_ollama_readme.py` passes, and `grep -n "#282" plugins/runner-ollama/README.md`
  finds nothing.
- [x] 3.2 In `contributing/runners.md`'s Ollama table, change the usage row to map `prompt_eval_count` less
  `prompt_eval_cached_count` to `inputTokens`, `prompt_eval_cached_count` to `cacheReadTokens` and `eval_count` to
  `outputTokens`. Leave the contract's own section to troupe#293. Verify: the row reads as the README does, and
  `uv run scripts/check.py` passes.
  (Done: the full check passed on f402e01, 3652 tests, as the guard ran it at commit.)

## 4. Check it end to end

- [x] 4.1 Run the live test against the local Ollama (`TROUPE_LIVE_OLLAMA=1 uv run pytest
  packages/troupe/tests/test_ollama_live.py`), and read the `result` it recorded. Verify: the test passes, and if the
  run made more than one request, its `usage` holds `cacheReadTokens`, with `inputTokens + cacheReadTokens` equal to
  the sum of its answers' `prompt_eval_count` in the transcript. Note what was seen under this task. The test
  runs one small model, so ask the owner before running it if anything else heavy is running.
  (Done on 2026-11-07, owner's go-ahead, with `TROUPE_LIVE_OLLAMA_MODEL=qwen3:0.6b` against Ollama 0.40.14:
  passed, wrote `out/hello.txt`. Two answers: prompt 1240 with 0 cached, then 1390 with 1241 cached. The result had
  `inputTokens` 1389, `cacheReadTokens` 1241 and `outputTokens` 296, and 1389 + 1241 = 1240 + 1390. Read through
  temporary prints in the test, reverted after the run.)
- [x] 4.2 Run `uv run scripts/check.py` and `openspec validate ollama-cache-read-tokens --strict`. Verify: both pass,
  and CI passes on Linux, macOS and Windows on the pull request's last code commit.
  (Done: both pass. After the last rebase onto main on 2026-11-09, CI run 42571790033 passed every job, Linux, macOS
  and Windows on Python 3.12 to 3.15, on 72aa5074, whose last code commit is e3e3b14e. Earlier heads passed too: run
  42539777989 on 10627b3b and run 42376532437 on 84a8638.)

## 5. Follow the merged contract (troupe#293, PR #312; design D5)

- [x] 5.1 Rebase onto main at 9d0b909 (#312 archived), resolving the README's and `contributing/runners.md`'s conflicts
  with text that corrects #312's statement that `prompt_eval_count` leaves out the cached tokens. Verify: the rebase
  completes, no conflict markers remain, and the Ollama row links the contract's "What usage counts".
- [x] 5.2 Report and subtract cache reads only when every answer reported a cached count beside its prompt count
  (runner-protocol, "A cache counter left out was not reported"): update the spec's "A request that reports no cached
  count" scenario, add design D5, and change the runner. Verify: the renamed test
  `test_when_an_answer_has_no_cached_count_no_cache_read_is_reported_or_subtracted` fails on d21fcc1's runner
  (`inputTokens` 400 with `cacheReadTokens` 20) and passes on the new one, with the other usage tests.
- [x] 5.3 Run the plugin's tests and the full check on the rebased branch. Verify: `uv run pytest plugins/runner-ollama`
  passes, and so does the guard's full check at commit.
  (Done: 249 passed; the guard's check at 565dea7 ran the `runner_ollama` scope and passed, and
  `scripts/check.py --scope docs` passed on it for the rebased README and contributing text.)

## Workflow follow-up

- Open a draft PR that closes troupe#282 and act on Claude's review of the last push, as CLAUDE.md says.
- Archive the change on the branch before the owner merges it.
- After the merge, comment on troupe#282 with the PR and the archived change, check it's closed, and check its card
  on the troupe roadmap board says Done.
- Mention on troupe#293 that the Ollama runner now follows its meaning, so the contract text is the only thing left.
