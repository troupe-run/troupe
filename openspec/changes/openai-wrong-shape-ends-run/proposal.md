# Proposal

## Why

The OpenAI runner retries any response it can't read as a broken stream (troupe#300, from the split review of #297).
That's right for a stream cut short, but not for a response the service finished in the wrong shape: a final event
whose tool-call arguments are an object, say, or a 200 with a plain JSON body instead of a stream. Retrying can't fix
those. Each retry resends the whole conversation, none is counted towards the token budget, and after five attempts
the run reports "Gave up after 5 attempts", which hides what was wrong.

## What Changes

- The runner tells a response **cut short** from one **finished in the wrong shape**:
  - Cut short, and still retried as a network failure: the stream ends before a final event, goes silent past the
    stream timeout, breaks, or ends in the middle of an event whose data isn't whole JSON yet.
  - Finished in the wrong shape, ending the run at once with an `error` result that names what was wrong: a finished
    event (its blank line arrived, or its data is whole JSON) that isn't JSON or has no type, or a final event whose
    response can't be read (a field of the wrong type, output that isn't a list).
- A 2xx response whose `Content-Type` is present and isn't `text/event-stream` ends the run at once, naming the type
  and the start of the body (the service's own message when the body is in OpenAI's error shape), and the body is
  recorded in the transcript. A response with no `Content-Type` is still read as a stream.
- When a wrong-shaped final event's `usage` can still be read, it's counted into the result's usage and cost, since
  the service did the work.
- The `openai-runner` spec says which is which. The runner's README failure tables say the same.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openai-runner`: "A broken stream is retried as a network failure" narrows to a stream cut short; a new
  requirement says a response finished in the wrong shape, or a 2xx that isn't a stream, ends the run with an error
  naming what was wrong, and isn't retried.

## Impact

- `plugins/runner-openai`: `stream.py` (tell an event ended by its blank line from one the body ended in, and raise a
  distinct error for a finished response that can't be read), `exchange.py` (end the exchange on it rather than
  retry; check a 2xx's `Content-Type`), `loop.py` (count a wrong-shaped response's readable usage), their tests, a
  new replay fixture, and `README.md`.
- No change to the runner protocol, its schemas, troupe core or other runners. No spec Purpose changes, so no
  infrastructure `oob` update.
