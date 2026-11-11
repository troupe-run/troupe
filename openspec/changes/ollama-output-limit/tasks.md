# Tasks

## 1. Before building

- [x] 1.1 Re-read `conversation.py`'s `_loop`, `_after` and `_call_tools`, and check D1 still holds: the cut check
  can sit in `_after` after the `turn` and before `_call_tools`, outside `_request`'s retry loop. If it can't, update
  this change (`/opsx:update`). Verify: the first apply commit's message says D1 holds, or the artifacts are updated
  and `openspec validate ollama-output-limit --strict` passes.
- [x] 1.2 Find every reference to the requirement "Each failure reports its reason" of `ollama-runner` (test
  comments, docs) and point it at "Each failed run reports its reason" (design D5); leave the OpenAI runner's own
  requirement of that name alone. Verify: `grep -rn "Each failure reports its reason" plugins/runner-ollama` finds
  nothing.

## 2. The runner (design D1, D2, D3)

- [x] 2.1 Write the tests first, in `tests/test_ollama_conversation.py`, replacing
  `test_a_cut_answer_is_a_warning_and_the_run_goes_on`: a cut text answer sends its `turn`, then an `error` result
  with `output-limit` naming the window and `contextLength`, and no `log` warning; a cut answer holding a `Write`
  call sends no `tool_call`/`tool_result`, writes no file and makes one request; no `retry` event; `eval_count` 81
  puts "after 81 tokens" in the message, and a missing or malformed `eval_count` leaves the count out; the result's
  `usage.outputTokens` includes the cut answer's `eval_count`. Verify: each fails on main's code for the stated
  reason (run them before 2.2).
- [x] 2.2 In `_after`, replace the `log` warning with `_RunEnded(message, "output-limit")`, the message as D2, built
  beside the context-length message. Verify: 2.1's tests pass.
- [x] 2.3 Update `tests/test_ollama_conversation_properties.py` for the cut case: wherever an invariant expects a
  text-only answer to end `ok`, or a tool call to run, an answer whose last line says `done_reason` `length` ends
  `error` with `output-limit` and runs none of its calls. Verify: the property tests pass, and fail with 2.2 reverted.

## 3. Fixtures (design D4)

- [ ] 3.1 Add the `cut-answer` and `cut-tool-call` scenarios to `tools/capture_ollama.py`, and capture both from the
  local Ollama (0.40.14, `qwen3:0.6b`), setting `contextLength` from the first request's prompt so the answer fills
  the window. Verify: each fixture's `answers.json` has a last line with `done_reason` `length`; its `events.json`,
  reviewed by hand, ends with an `error` `result` with `output-limit` and holds no `tool_call` from the cut answer;
  `provenance.json` records the version, model, date, window and direction used.
- [ ] 3.2 Add both to the fixture tests (`test_there_are_fixtures_for_each_shape` if it lists shapes, the replay, and a
  test that `cut-tool-call`'s recorded answer is what D4 says it is: a partial call, raw text, or nothing). Verify:
  `uv run pytest plugins/runner-ollama/tests/test_ollama_fixtures.py` passes, and the replay fails with 2.2 reverted.

## 4. Docs

- [ ] 4.1 `plugins/runner-ollama/README.md`: the window section (a cut answer ends the run, and what Ollama sends for
  a cut tool call, from 3.1), the run-event table's `done_reason` `length` row (`result` `error`, `output-limit`), the
  reasons paragraph, how a run ends, and the line that says what to do instead is Decision #279 (now decided, with
  #307 and #310 for what follows). Verify: `test_ollama_readme.py` passes, and `grep -n "log. warning" README.md`
  finds no cut-answer row.
- [ ] 4.2 `contributing/runners.md`: the Ollama mapping's `done_reason` `length` row. Verify: `uv run scripts/check.py`
  passes, including its docs checks.

## 5. Land it

- [ ] 5.1 Run `uv run scripts/check.py` in full and keep its log. Verify: it passes; then commit (signed, with a
  Signed-off-by trailer) and open a draft PR that `Closes #309`.
- [ ] 5.2 Act on Claude's review of the last push, then mark the PR ready once the review leaves nothing open.
  Verify: CI passes on Linux, macOS and Windows on the head; cite the run.
