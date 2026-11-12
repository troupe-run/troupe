# Tasks

## 1. A test that shows the race

- [x] 1.1 Add a harness test in `plugins/runner-openai/tests/` that makes the run finish before a `request()` is
  answered (start, wait until `received` holds the result, then send the second `run/start`), and checks that
  `until_result()` still returns the result. Verify: it fails on main with `queue.Empty`, before any harness change.
- [x] 1.2 Do the same for the scripted harness (a script with no `wait` step, then a second `run/start` once the
  result is in `received`). Verify: it fails before 2.3.

## 2. The harnesses keep what a request reads past (D1)

- [x] 2.1 OpenAI harness: `request()` sets aside what it reads past; `until_result()` reads that first, and clears it
  up to the result. Verify: 1.1 passes; the whole `plugins/runner-openai` suite passes.
- [x] 2.2 Ollama harness: the same. Verify: a test like 1.1 against the Ollama fake passes, and the whole
  `plugins/runner-ollama` suite passes.
- [x] 2.3 Scripted harness: the same, plus an `until_result()`. Verify: 1.2 passes; the whole `plugins/runner-scripted`
  suite passes.
- [x] 2.4 Claude Code: move `_until_result` into `claude_harness.py` as `until_result()`, with the set-aside list.
  Verify: the whole `plugins/runner-claude-code` suite passes.

## 3. The OpenAI test checks a second start mid-run (D2)

- [x] 3.1 Add `Gate(event)` to `fake_endpoint.py`, with tests in `test_openai_fake_endpoint.py`: the stream stops at
  the gate until it's opened, and a fake that stops ends a gate that never opens. Verify: both tests pass.
- [x] 3.2 Rewrite `test_a_second_run_start_is_refused_and_the_first_run_goes_on` as D2's three steps, with a failure
  message naming the first run's result. Verify: it passes; with the gate never opened it fails at `TIMEOUT` with that
  message (run once by hand, recorded in the PR).

## 4. The scripted test (D3)

- [x] 4.1 Rename the scripted second-start test to what it checks, and read with `until_result()`. Verify: it passes.

## 5. Verification

- [x] 5.1 Flake hunt on macOS under load, the OpenAI test alone: `uv run scripts/flake_hunt.py --workers 8 --rounds 15
  --load 8 -k test_a_second_run_start plugins/runner-openai/tests/test_openai_runner.py` (the run that found 8 of 120
  failing). Verify: 0 failures in 120 runs, recorded on #392.
- [x] 5.2 The same hunt for the scripted test. Verify: 0 failures.
- [x] 5.3 `uv run scripts/check.py` passes.

## Workflow follow-up

- Draft PR closing #392; act on Claude's review; mark ready; archive on the branch; the owner merges.
- After the merge: comment on #392 with the PR and the archived change; check the issue is closed and its card Done.
