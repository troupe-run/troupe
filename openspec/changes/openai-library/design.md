# Design: the OpenAI runner uses the openai package

## Context

- **Today** the runner (`plugins/runner-openai`) talks to a Responses API service through `service.py`: `urllib` with
  a handler that refuses redirects, a socket captured as it connects (so the stream timeout can be set on it and
  another thread can shut it down), proxies skipped for a loopback endpoint, and a line reader with a 16 MiB line cap.
  `stream.py` parses server-sent events by hand into a `Reply` from the final event's response object.
  `exchange.py` retries and records each request body, stream line and error body as bytes. Cancel shuts the socket
  down, which wakes the worker.
- **`openai-style-runner` design D3** turned the `openai` package down for three reasons beyond habit: it retries on
  its own terms, follows redirects with its own header rules, and hides the wire bytes the transcript had to keep.
- **Decision #319** (owner, 2026-11-07) answers each: the library's retries are off and troupe's loop retries; redirects
  are never followed; the credential stays in its header; and a library-backed runner's transcript keeps what the
  library exposes, not wire bytes. **#333** made the extras (`troupe-run[<runner>]`, `all`, `runner.not-installed`)
  and the licence check. **#415's Anthropic runner** is the precedent built since: the same code generator's library
  (`anthropic` 2.8.0, on `httpx2`), behind a seam module, with cancel ending the process (anthropic-runner design D1,
  D4, D9, D10, D11).
- **`openai` 3.52.0** (Apache-2.0, Python ≥ 3.10, released 2026-11-16, roughly one release every two days), read from
  its source and probed against the runner's fake endpoint on 2026-11-17 (scratchpad, not committed):
  - depends on `anyio`, `httpx2`, `jiter`, `pydantic`, `sniffio` and `typing-extensions`, all already locked for the
    Anthropic runner (`httpx2` 2.16.0); no OpenTelemetry;
  - its default client follows redirects and retries twice; given `max_retries=0` and an `httpx2.Client` with
    `follow_redirects=False`, a `307` raises `APIStatusError` after one request;
  - reads `OPENAI_API_KEY`, `OPENAI_ADMIN_KEY`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`, `OPENAI_WEBHOOK_SECRET`,
    `OPENAI_BASE_URL` and `OPENAI_CUSTOM_HEADERS` when they're not given, and `OPENAI_LOG` at import;
  - refuses to build a client with no credential unless `Authorization` is omitted per request;
  - sends `Authorization: Bearer <key>`, its own `User-Agent` and `X-Stainless-*` headers (OS, architecture, Python,
    package version, retry count, read timeout);
  - its SSE decoder dispatches an event only on its blank line (an event the body ends without one is dropped), decodes
    each line as UTF-8 (raising `UnicodeDecodeError` otherwise), parses each event's data with `json.loads` (raising
    `JSONDecodeError`, whose `doc` is the data), imposes no line or event size limit, and raises `APIError` for an event
    whose data has a truthy top-level `error`;
  - builds each event with `construct` (no validation): an unknown event type or a field of the wrong type is kept as
    sent, and `to_dict(mode="json")` gives it back, but pydantic prints serialiser warnings for each wrong type unless
    told not to (`warnings=False`).

## Goals / Non-Goals

**Goals:**

- The runner sends every request through `openai`, and troupe stops maintaining its own HTTP client and SSE parser.
- Every behaviour `openai-runner` specifies stays, proved by today's fixtures and tests replayed through the same fake
  endpoint, with two edges the library forces made explicit in the spec (D5, D8), both accepted by the owner (2026-11-17).
- Each of #319's guarantees is set by the runner and pinned by a test that would fail on the library's default.
- `troupe-run[openai]` as #333 designed it.

**Non-Goals:**

- Any change to what the runner sends or does beyond what the library forces: the request body, options, limits,
  failure table, compaction and fixtures stay.
- The library's typed request parameters or response helpers (`output_text`, `parse`): the runner keeps its own
  reading of the response object, which the wrong-shape rules depend on.
- The async client, the Realtime or WebSocket transport, Azure or workload identity.
- Re-capturing fixtures: their `replies.json` are what a service sent on the wire, replayed by the fake endpoint, and
  stay valid; the capture tool keeps recording wire lines with the standard library, since that's what replay needs.

## Decisions

### D1. `openai`, pinned, behind one seam module

The runner depends on `troupe-plugin-sdk` and `openai==3.52.0`. `service.py` alone imports `openai` and `httpx2`; the
rest of the runner works with its own types: a request's parameters as a dict, each stream event as a dict, and a
closed set of failures in `failures.py` (which imports neither). `library.py` holds what the runner sets around the
library (its environment and loggers) without importing it, so the handshake isn't kept waiting for the import. An
import contract pins the seam, as for the Anthropic runner. 3.52.0 is the newest release when this was proposed; a
bump is its own change, rerun against the fixtures and the live test.

**What changed since `openai-style-runner` D3:** "no dependency beyond the SDK" is no longer the rule (#319, point 1);
the library's retries are turned off (D3); its redirects are turned off by giving it the runner's HTTP client (D3);
and the transcript's wire bytes are given up for what the library exposes, which #319 chose over hooking each library's
transport (D6). The extra keeps an install that doesn't use the runner free of the library (#333).

**Alternatives:** the library for sending and the runner's own SSE parser over the raw response
(`with_streaming_response`, `iter_lines`). It would keep wire bytes and today's stream rules exactly, but keeps the
half of the protocol #319 asked to stop rebuilding, and #331 asks for the library's events in the transcript. The
async client: the runner's threads already work with the sync one, as the Anthropic runner's do.

### D2. The library finds nothing of its own

- The runner removes every `OPENAI_*` variable from its own environment before it imports or builds the library
  (`library.py`). Perform passes the runner only `OPENAI_ENVIRONMENT` (proxies and certificates), so none reach it
  today; this keeps it so if the runner is started another way.
- The client gets `base_url` (the runtime's endpoint), `api_key`, `max_retries=0`, `timeout` and `http_client`
  explicitly, and no organisation, project or default headers.
- **With no credential** the library must send none. It won't build a client without one, so it gets a fixed
  placeholder that is never a key (`"no-credential"`), and every request passes `extra_headers={"Authorization":
  Omit()}`, which the library accepts as "explicitly omitted" and which removes the header. A test pins that no request
  carries `Authorization` with `OPENAI_API_KEY` set.

### D3. The HTTP client, retries, redirects and timeouts

- The runner builds the library's `httpx2.Client` with `follow_redirects=False`, so a 3xx reaches the runner as
  `APIStatusError`, classified as today (`configuration`, naming the status and `Location`). A test pins that nothing
  connects to the location.
- `max_retries=0`; the runner's loop (`exchange.py`) retries exactly as today: 429 with `Retry-After` within the cap,
  5xx, network errors, timeouts and cut streams, with its named attempts and backoff.
- Timeouts: one `httpx2.Timeout` from named settings, given to both the client and the library, so the library's
  ten-minute default never applies: connect `CONNECT_TIMEOUT_SECONDS` (30), pool the same, read
  `STREAM_TIMEOUT_SECONDS` (120), write `WRITE_TIMEOUT_SECONDS` (new, 30). Today the connect timeout also covered
  waiting for the response's status; with `httpx2` that wait is a read, so it's bounded by the stream timeout. Both are
  named and both bound the request.
- **Proxies and TLS** are chosen by the runner, as `urllib` chose them: the client is built with `trust_env=False`,
  its proxy is the one `urllib.request.getproxies()` names for the endpoint's scheme unless `proxy_bypass` (which
  reads `NO_PROXY`) says not to, with none ever for a loopback endpoint (today's rule), and its TLS context is
  `ssl.create_default_context()`, which reads `SSL_CERT_FILE` and `SSL_CERT_DIR`.

### D4. Reading the stream through the library

`service.py` returns the response's status and headers and an iterator of events, each `to_dict(mode="json",
warnings=False)`: the event as the service sent it, without serialiser warnings. The reader (`stream.py`) keeps today's
reading of the final event's response object (`read_response`, unchanged), so every wrong-shape rule holds: the library
validates nothing, and the probe showed arguments as an object, output as a number and a cached count as a string all
reaching the runner as sent. Failures map as:

| The library raises | The runner's failure |
|---|---|
| `APIStatusError` (any non-2xx, 3xx included) | a status error: status, headers, body, classified as today |
| `APITimeoutError`, `APIConnectionError`, an `httpx2` error, during the request or the stream | a network failure, retried |
| `UnicodeDecodeError` while reading the stream | a network failure, retried, as today |
| `JSONDecodeError` for an event's data | wrong shape (`engine`), quoting the start of its `doc`, as today |
| `APIError` for an event whose data has a top-level `error` | the reply's `error` status with that failure, as today's `error` event |

A 2xx whose `Content-Type` is present and isn't `text/event-stream` is checked on the stream's response before any
event is read, as today; its body is read and recorded.

### D4a. A named cap on a stream's lines, in the transport

**Owner decision (2026-11-17):** keep a size cap, enforced under the library, not by touching its private decoder.
The runner's `httpx2.Client` is built on a transport that wraps the default one (`_CappedTransport`), whose responses'
byte streams count the bytes since the last line ending. A line longer than `STREAM_LINE_MAX_BYTES` (16 MiB, as today)
raises an `httpx2.ReadError` subclass naming the limit, before more is buffered; the library wraps it as a connection
error, and the runner reports it as a broken stream (`network`), with the limit in its message, as today. The cap
applies to every response body the client reads, so an error body or a 2xx JSON body is bounded too
(`ERROR_BODY_MAX_BYTES` stays the cap on how much of such a body is recorded and parsed).

The client decodes `Content-Encoding` above the transport, so the cap would count compressed bytes: a gzip line of a
few KB could decode to gigabytes (review of #440). So the client asks for none (`Accept-Encoding: identity`, as urllib
did), and the transport refuses a response sent encoded anyway, before reading its body, as a network failure naming
the encoding and the limit. A non-2xx sent encoded isn't refused: its status still classifies the failure, so its
body is read raw up to `ERROR_BODY_MAX_BYTES` and decoded (gzip or deflate, through zlib) into at most as many bytes.

**Not shared with #332:** the Ollama runner moved to `httpx` 0.28.1, while `openai` is built on `httpx2`; two
different packages, so neither a pin nor a transport can be shared. A stdlib-only line counter in the plugin SDK could
be, as a follow-up if both are kept.

### D5. When an event counts as finished

The library dispatches an event only on its blank line. So a body that ends right after a final event's `data:` line,
before its blank line, now drops that event and is retried as a cut stream; today it was read
(openai-wrong-shape-ends-run design D1). The spec's broken-stream and wrong-shape requirements say so, with a scenario
for it. It's the conservative side: the request is sent again, which costs one request and acts on nothing that wasn't
finished. Keeping today's rule would need replacing the library's private SSE decoder. Recorded streams from OpenAI and
Ollama end with their blank line, so no recorded run changes.

### D6. The transcript, and what it loses

- `sent`: each request's parameters as passed to the library, compact JSON, recorded once per request, before its
  attempts, as today. The library serialises the same object; the body on the wire differs only in key order and spacing.
- `received`: each event as the library parsed it, compact JSON, with a lone surrogate kept as its JSON escape (as the
  Anthropic runner records it, host-robustness design D3b); each error body and each 2xx body that isn't a stream, as
  bytes.
- `note`: each response's status with the headers named in `defaults.py`, and each stream abandoned, unchanged.

**Compared with the wire** it loses the SSE framing (`event:` lines, blank lines, comments, `id:` and `retry:`), an
event the library drops (one without its blank line at the end of the body, D5), and the request's exact bytes and
library-added headers (which were never recorded). Event data keeps every field, known or not, since the library
constructs without validation; a test pins an unknown field surviving.

### D7. Lone surrogates

As #437 left it, read through the library: the event dict is recorded with each lone surrogate as its escape, then read
with `p.unicode_text_counted`, and each replacement reported through `on_lost`; an error body's message the same way.

### D8. Cancel and end of input end the process

Closing the library's stream or client from another thread doesn't wake a blocked read (anthropic-runner design D9,
probed there on the same `httpx2`). So the runner keeps a flag, set under the output lock, saying a request is in flight;
on cancel and end of input the main thread answers, flushes, and, with a request in flight, returns at once to `main`'s
`os._exit`, which closes the connection; between requests the worker finishes on its own within `STOP_GRACE_SECONDS`.
A runner process holds one run, so nothing else is lost, and no `result` follows, since the stop flag is set first.
`Call.abort` and the captured socket go. **The library is imported in the worker**, after `run/start` is answered, and
warmed by a background import at start, so the handshake doesn't wait for it.

### D9. The library's logging

`library.py` points the `openai`, `httpx2` and `httpcore2` loggers at standard error, warnings and above only, masked
and cut to a named size, never standard output, and `OPENAI_LOG` is removed before the library is imported (it's read
at import). Serialiser warnings are off at the source (D4).

### D10. Shipping it

- `troupe-runner-openai` moves from `troupe-run`'s dependencies to the `openai` extra and `all`; core's runner table
  marks `openai` `in_extra=True`; the install page gains a row; the release configuration keeps the bundle's commits
  out of release pull requests while the plugin is unreleased. `scripts/bundle.py`, `scripts/release_config.py` and the
  install docs test check each.
- **Licences and platforms:** `openai` is Apache-2.0 and its dependencies are those already checked for `anthropic`;
  `scripts/runner_licences.py` checks the lock. The install check installs `troupe-run[all]` on Linux, macOS and Windows
  for every supported Python, which now includes `openai`.
- Tests of core that run the OpenAI runner (`test_perform_openai.py`, conformance) need the plugin installed, which the
  workspace's dev install does; nothing changes for them.
- **#332 (Ollama onto `ollama`) runs in parallel** and edits the same extras, runner table, install page and the `cli`
  audition requirement. Whichever merges second rebases, keeps the other's wording, and re-archives if the archive
  commit conflicts.

### D11. Testing

- **Differential first:** before the seam changes, the tests that pin behaviour this change must keep (fixture replay,
  the failure table, redirects, retries, timeouts, the credential, cancel) run green on today's runner and stay
  unchanged. New tests for the library's guarantees (variables, `OPENAI_LOG`, only the runner retries, a held
  connection) are written first and pass on today's runner too, since they state what must hold either way. The two
  that state D5's and D6's changes (a final event without its blank line; the transcript's records) fail on today's
  runner by design, and say so.
- Unit tests at the seam: the client's settings (no redirects, no retries, timeouts), the failure mapping table (D4),
  an unknown field surviving to the transcript.
- Conformance (`check_runner`) against the fake endpoint, and the live test (`TROUPE_LIVE_OPENAI=1`, the owner's key)
  once before the PR is marked ready, or the owner's word to go without it.

## Risks / Trade-offs

- **A library that changes every few days.** → Pinned exactly; one seam module; fixtures and request-shape tests catch
  what a bump changes.
- **The library has no line or event size limit.** → The runner's transport caps each line (D4a, owner's decision),
  as the hand-written reader did.
- **A final event without its blank line is retried** (D5). → One extra request in a case no recorded service shows.
- **The transcript loses the SSE framing** (D6). → What #319 chose; the events keep every field.
- **Cancel ends the process mid-request** (D8). → One run per process; the same as the Anthropic runner, and the
  service sees the connection closed, as the spec asks.
- **The library's headers** (`X-Stainless-*`, its `User-Agent`) now reach the service: OS, architecture and Python
  version. → Not a credential or anything of the person's; OpenAI's own clients send them.
