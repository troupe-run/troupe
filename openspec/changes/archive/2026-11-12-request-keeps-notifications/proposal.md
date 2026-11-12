# Proposal: a request doesn't lose the notifications it reads past

## Why

`test_a_second_run_start_is_refused_and_the_first_run_goes_on` (troupe-run/troupe#392) fails now and then on a loaded
machine. It isn't the runner. Run under load (`flake_hunt.py`, 8 workers with 8 load processes, the test alone,
2026-11-12), it failed 8 times in 120 runs, each with the CI failure's `_queue.Empty` in `until_result`. With the
order forced (the test waits until the run is over before sending the second `run/start`), it fails every time:

- The runner refuses the second `run/start` with `runner.already-started`, and the first run sends `init`, `turn` and
  an `ok` result, as the runner contract says it should.
- The harness's `request()` reads messages until it finds its own response. Everything before that response goes
  into `received` but is taken off the stream. When the run's `result` gets out before the refusal, `request()` reads
  past it, and `until_result()` then waits 30 s for a result that has already gone by.

So the test races the run it starts. On a quiet machine the refusal almost always comes first, because the run needs
a round trip to the fake endpoint. Under load the order can go either way. The runner needs no fix. The harness does,
and so does the test, which never makes sure the first run is still going when the second `run/start` arrives.

## What Changes

- **A request sets aside the notifications it reads past, and `until_result()` reads them first.** In the OpenAI
  harness, and for the same reason in the Ollama and scripted harnesses and the Claude Code tests' `_until_result`, a
  run's result that came before a response can't be missed. `message()` and `rest()` still read only what comes next,
  because the cancel and shutdown tests use them to check that nothing follows an answer (design D1).
- **The OpenAI test holds its first run open until the second `run/start` has been refused.** The fake endpoint gets
  a gate: a stream item that waits until the test opens it, or the fake stops. The test waits for the runner's request
  (the `REQUEST_WITHIN` bound the stop tests already use), sends the second `run/start` and checks it's refused, then
  opens the gate and waits for the result. Then the name's "the first run goes on" is what the test checks every
  time, not on most runs (design D2).
- **It still fails if the first run never ends**, at the harness's named `TIMEOUT`, with a message saying it waited
  for the run's result.
- **The scripted runner's matching test reads to the result rather than one notification.** It has the same race,
  hidden behind a 300 ms `wait` step in its script. The scripted runner has no step that waits for the test, and
  adding one would change its script language, so the test is named for what it checks (design D3).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. The runners already behave as their specs say. This changes test harnesses and tests only, so the change sets
`skip_specs`.

## Impact

- `plugins/runner-openai/tests/`: `openai_harness.py` (`request`, `until_result`), `fake_endpoint.py` (the gate),
  `test_openai_runner.py`, `test_openai_fake_endpoint.py` (the gate's own tests).
- `plugins/runner-ollama/tests/ollama_harness.py`, `plugins/runner-scripted/tests/scripted_harness.py` and
  `test_scripted_runner.py`, `plugins/runner-claude-code/tests/claude_harness.py` and `test_claude_code_runner.py`.
- No runner, SDK or protocol code changes. Each plugin's tests stay self-contained: the harnesses aren't shared.
