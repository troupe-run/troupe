# Tasks

## 1. Guard what must stay the same

- [x] 1.0 Before task 3.2, confirm the `Content-Type` OpenAI sends on a streamed `/v1/responses` reply: the owner
  runs the request with their key and pastes the response headers. Verify the media type is `text/event-stream`; if
  it isn't, stop and revise design D4 with the owner before building it. (Ollama was checked on 2026-11-07:
  `text/event-stream` streamed, `application/json` not.) Done 2026-11-07: the owner's streamed request to OpenAI
  (`gpt-6-luna`) was answered `HTTP/2 200` with `content-type: text/event-stream; charset=utf-8`.
- [x] 1.1 Write the property test (design D6) in `plugins/runner-openai/tests/test_openai_stream.py`: cut the recorded
  OpenAI and Ollama `stream-1.txt` at every byte offset, feed the lines to `StreamParser`, and check each cut either
  reads the same reply as the whole stream or raises `StreamError` and nothing else. Verify it passes on the code as
  it is before any change, and commit it on its own.

## 2. Tell a finished event from a cut one

- [x] 2.1 Add `ShapeError` to `stream.py` (not a `StreamError` subclass), carrying the response's `usage` when it's an
  object; raise it from `_string`, `_dict` and `read_response`'s checks, and from `_dispatch` for a finished event that
  isn't JSON or has no type, keeping `StreamError` for an event `end()` dispatched whose data isn't JSON and for a
  stream with no final event (design D1, D2). Update the module and `StreamError` docstrings to say which is which.
  Verify by splitting `test_an_event_that_cant_be_read_breaks_the_stream` into finished cases (`ShapeError`, naming
  what was wrong) and cut cases (`StreamError`), adding a case for a `function_call` whose `arguments` is an object,
  and running `uv run pytest plugins/runner-openai/tests/test_openai_stream.py` with 1.1's property test still green.

## 3. End the exchange on the wrong shape

- [x] 3.1 In `exchange.py`, catch `ShapeError` and raise `ExchangeFailedError` at once with D3's message and the
  error's `usage`, sending no `retry` and recording no `dropped` record; give `ExchangeFailedError` an optional
  `usage`. Verify with exchange tests that a wrong-shaped final event and a finished non-JSON event each make one
  request, no retry, and fail with a message naming what was wrong and saying retrying can't fix it; and that
  `test_a_stream_cut_mid_tool_call_is_dropped_and_retried_as_network` still passes.
- [x] 3.2 Add `Response.body()` to `service.py` (up to `ERROR_BODY_MAX_BYTES`), and in `_attempt` check a 2xx's
  `Content-Type` as D4 says: present and not `text/event-stream` records a `body` record and raises
  `ExchangeFailedError` naming the status, the type and the service's message (or the body's start); absent reads a
  stream. Verify with exchange tests for a 200 `application/json` body (one request, no retry, a `body` record, the
  message), a 200 in OpenAI's error shape (its message quoted), `text/event-stream; charset=utf-8` and a missing
  `Content-Type` (each read as a stream), and a service test for `body()` on a body cut short.
- [x] 3.3 In `loop.py`, add an `ExchangeFailedError`'s `usage` to the run's spend before making the result (design
  D5). Verify with a loop test of the spec's "Readable usage beside unreadable output" scenario (`inputTokens` 300,
  `outputTokens` 30, `turns` 2), and one where the wrong-shaped response's usage can't be read (the result has no
  usage).

## 4. Through the runner, and the docs

- [x] 4.1 Add a "wrong shape" and a "not a stream" ending, each holding the canary, to `SCRIPTS` in
  `test_openai_runner.py`. Verify the parametrized
  `test_the_credential_is_nowhere_in_what_the_runner_writes_however_the_run_ends` passes for both.
- [x] 4.2 Add the replay fixture `plugins/runner-openai/fixtures/responses/wrong-shape`: the recorded OpenAI tool-loop
  `stream-1.txt` with its `function_call`'s `arguments` made an object, a `provenance.json` saying it was derived and
  how, and expected events ending in the error result after one request. Verify `uv run pytest
  plugins/runner-openai/tests/test_openai_fixtures.py` replays it.
- [x] 4.3 Update `plugins/runner-openai/README.md`: the retried table's `network` row says a stream cut short, "How a
  run ends" gains a response finished in the wrong shape and a 2xx that isn't a stream, and the transcript section
  says a non-stream 2xx's body is a `body` record. Verify `uv run pytest plugins/runner-openai/tests/test_openai_readme.py`
  passes and the tables match the spec delta.

## 5. Whole-change checks

- [x] 5.1 Run `uv run scripts/check.py` and verify it passes, with the openai runner's tests, mypy --strict and ruff
  clean. Done 2026-11-07 on 26dcf86: the full check passed every gate (tests in 188 s); the commit's scoped check
  passed 3694 tests.
- [ ] 5.2 Ask the owner to run the opt-in live tests (`TROUPE_LIVE_OPENAI=1` in `packages/troupe/tests/test_openai_live.py`,
  and the Ollama live test against a local Ollama if it's running) and verify both pass, so D4's `Content-Type` check
  is shown to accept the real services' streams. Record the result in this task. Correction: `test_ollama_live.py`
  runs the Ollama runner, which this change doesn't touch; the OpenAI runner's live test pointed at local Ollama is
  the one that does. Ollama, 2026-11-07 on 26dcf86: `TROUPE_LIVE_OPENAI=1
  TROUPE_LIVE_OPENAI_ENDPOINT=http://127.0.0.1:11434/v1 TROUPE_LIVE_OPENAI_MODEL=qwen3.5:4b` passed (succeeded,
  wrote and read back `out/hello.txt`). OpenAI: waiting on the owner.
- [x] 5.3 Run `openspec validate openai-wrong-shape-ends-run --strict` and verify it passes, and that the spec delta,
  the code and the README agree. Done 2026-11-07: valid; the delta's requirements, the README's retried and "How a
  run ends" rows, and the exchange's handling each name the same cases (cut short retried; finished wrong shape and
  a non-stream 2xx end the run; the fixture list includes wrong-shape).

## Workflow follow-up

- Open a draft PR that closes troupe-run/troupe#300, act on Claude's review of the last push, then mark it ready.
- Archive the change on the branch before the owner merges.
- After the merge, check #300 is closed and its card says Done, and comment with the PR and the archived change.
