# Design

## Context

The runner reads each response with `StreamParser` (`stream.py`), which raises `StreamError` for anything it can't
read: a stream that ended without a final event, an event that isn't JSON or has no type, and a final event whose
response object has a field of the wrong type. `exchange` (`exchange.py`) catches `StreamError` beside
`NetworkError` and retries both as `network`, recording a `dropped` transcript record. A 2xx's `Content-Type` is never
looked at, so a plain JSON body has no `data:` lines, reads as a stream that ended before its final event, and is
retried too. The archived openai-style-runner design (D4, D8) put "a line that isn't a valid event" in the retried
row; this change splits that row. See proposal.md for why.

`Response.lines()` (`service.py`) strips each line's ending, so the parser can't see whether the body's last line was
whole; it can see whether an event was ended by its blank line (`feed("")`) or by the body ending (`end()`).

## Goals / Non-Goals

**Goals:**

- A stream cut short at any point is still retried, never ended as the wrong shape. This is the non-goal that
  matters most, and a property test falsifies it (D6).
- A response the service finished can't be retried, whatever is wrong with it.

**Non-Goals:**

- A line longer than `STREAM_LINE_MAX_BYTES`, or a line that isn't UTF-8, stays a broken stream (`NetworkError` from
  `service.py`). The first is the runner's own limit cutting the read, so it can't tell whether the line was whole;
  the second is raised below the parser. Neither was raised by the issue.
- `response.failed` and `error` events keep their rules (retried only for `SERVICE_FAILURE_CODES`). Their readers stay
  as lenient as they are now.
- Other runners (the Ollama runner has its own stream reader).

## Decisions

### D1. Finished or cut short: decided per event, by whether its data is whole

An event is **finished** when its blank line has arrived, or when the body ended after it and its data parses as
JSON. Only an event the body ended inside, whose data isn't whole JSON, is **cut short**, as is a stream that ends
with no final event at all. Anything wrong with a finished event is the wrong shape.

The JSON test covers a cut that lands just after a final event's `data:` line, before its blank line: the existing
"a last event without its blank line is still read" behaviour stays, and a whole JSON object can't be half of one.

*Alternatives:* retry a wrong-shaped response once before ending (still resends the whole conversation, uncounted,
for a service that answered the same way once already); end on anything unreadable, partial events included (would
turn real network cuts into failed runs, the regression D6 guards against).

### D2. A distinct exception, not a subclass of StreamError

`stream.py` gains `ShapeError`, raised for a finished event that can't be read, and carrying the response's `usage`
when that can be read (D5). It is not a `StreamError` subclass: `exchange` catches `StreamError` to retry, and a
subclass would be retried by that clause unless every `except` were ordered just so. `StreamError` keeps its meaning,
the stream was cut short, and its docstring says so.

The helpers that raise today (`_string`, `_dict`, the checks in `read_response`) raise `ShapeError`: they only ever run
on a finished event. `_dispatch` raises `ShapeError` for a finished event that isn't JSON or has no type, and
`StreamError` when the event was dispatched by `end()` and its data isn't JSON.

### D3. The exchange ends on ShapeError, with words that say retrying can't help

`exchange` catches `ShapeError` and raises `ExchangeFailedError` at once, with no `retry` event and no `dropped`
record (nothing is dropped to be retried; the stream lines are already in the transcript). The message is
`The service's response can't be read: <what the parser said> Retrying can't fix a response the service finished, so
the run ends here. Check that the runtime's endpoint serves OpenAI's Responses API.` The parser's own messages stay
the "what": they name the field, and the wrong type in words rather than as a Python type name, such as "The
response's tool call's arguments is an object, not text."

### D4. A 2xx is a stream only when its Content-Type says so, or says nothing

After a 2xx opens, `_attempt` reads `Content-Type`: its media type (before any `;`, stripped, lower-cased) must be
`text/event-stream`. When it's present and something else, the runner reads the body up to `ERROR_BODY_MAX_BYTES`
(a new `Response.body()` beside `lines()`), records it as a `body` record, and raises `ExchangeFailedError`:
`The service answered HTTP 200 with application/json, not the stream (text/event-stream) the runner asked for:
<message> Check that the runtime's endpoint serves OpenAI's Responses API with streaming.` The message is
`_service_error`'s, the same reading a non-2xx body gets: the service's own message for OpenAI's error shape, else
the body as text cut to the summary limit. A body that can't be read whole says so in place of the message; the
content type alone decides the outcome.

An absent `Content-Type` falls through to reading a stream (the project's rule: only an absent input may fall
through). A stream with no header that turns out not to be one still meets D1's rules.

*Alternative:* sniff the body (a first line starting `{`). Rejected: the runner sends `Accept: text/event-stream`, and
the header is the service's answer to it; sniffing would guess where the service said.

### D5. A wrong-shaped final event's readable usage is counted

When a final event's `response` is an object and its `usage` is an object, `ShapeError.usage` carries it.
`ExchangeFailedError` gains `answered` (the service finished a response the run must count) and an optional `usage`,
and when `answered` is true the loop adds the usage to the run's spend (`_Spend.add`, which already refuses a usage
it can't read, so an unreadable one leaves the result without usage) before making the result. Every other failure
has `answered` false and counts nothing, as before. The response counts as a request in `turns`, as it was one.
A failed response's usage stays uncounted, as the archived D9 says: this is only for a response the service
completed in the wrong shape, where it did the work.

### D6. Tests, including the one that guards against the regression

- `test_openai_stream.py`: the existing "event that can't be read" cases are split into finished (`ShapeError`) and
  cut short (`StreamError`); a property test cuts the recorded OpenAI and Ollama streams at every byte offset and
  checks that each cut either reads the same reply as the whole stream or raises `StreamError`, never `ShapeError`.
  It's written first and passes on main (where every failure is a `StreamError`), as the differential-testing rule
  asks.
- `test_openai_exchange.py`: a wrong-shaped final event, a finished non-JSON event and a 200 JSON body each send one
  request, no `retry`, and fail with the message; a `text/event-stream; charset=utf-8` and a missing `Content-Type`
  are read; the 200 JSON body is in a `body` record.
- `test_openai_loop.py`: the usage scenario.
- `test_openai_runner.py`: the credential canary's `SCRIPTS` gain a "wrong shape" and a "not a stream" ending, each
  holding the canary, so the new messages are shown masked.
- A replay fixture, `fixtures/responses/wrong-shape`, built from the recorded OpenAI tool-loop stream with its
  `function_call`'s `arguments` made an object, whose expected events end in the error result after one request.

## Risks / Trade-offs

- [A proxy that corrupts a whole event, keeping its framing, now ends the run where it used to be retried] → The
  result names what was wrong, and re-running the actor costs one request. Corruption that keeps line framing is rare
  next to a service that answers in the wrong shape every time.
- [An OpenAI-compatible server that streams with another `Content-Type` now fails at once] → The message names the
  type it sent. The recordings don't keep headers, so it was checked live on 2026-11-07: Ollama (`qwen3.5:4b`,
  `/v1/responses`) answers a streamed request with `Content-Type: text/event-stream` and a `"stream": false` one
  with `application/json`, the case this change ends on. The owner checked OpenAI the same day (`gpt-6-luna`): a streamed
  request is answered 200 with `text/event-stream; charset=utf-8`, which D4 accepts once the parameter is dropped
  (task 1.0), so the opt-in live tests (`TROUPE_LIVE_OPENAI=1`, the Ollama live test) are run before the
  change is called done.
- [Cutting the recorded streams at every byte is slow] → The streams are a few kilobytes and the parser is fed lines
  directly, with no endpoint; if it's slow on Windows CI, a Hypothesis sample of offsets replaces the full sweep.
