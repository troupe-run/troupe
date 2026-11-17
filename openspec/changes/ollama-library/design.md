## Context

The Ollama runner (`plugins/runner-ollama/`) talks to Ollama through `client.py`, about 250 lines on the standard
library's `http.client` (local-model-runner design D2). `Client` has four calls:

- `version` and `show`, the preflight's;
- `chat`, which streams one `/api/chat` answer as lines of raw bytes;
- `close`, which shuts down the socket in flight from another thread, waking a blocked read on every platform (D3).

It classifies failures into `UnreachableError`, `RetryableError` (`network` or `server`), `EngineError` and
`StoppedError`, so `conversation.py` and `runner.py` only decide what to do with them. Everything above `Client` works
on the exact bytes of each request and each answer line. Those bytes are what the transcript, the fixtures and the
compaction logic rely on.

Decision #319 point 4 moves the runner onto a maintained library and removes the spec's no-dependency requirement.
#333 (merged as #338) made such a runner an optional extra of `troupe-run`. It also wrote the guarantees down once,
as runner-protocol requirements:

- retries only through troupe's named limits;
- no redirects, and the credential only in its header;
- cancel within the grace period;
- the transcript;
- pinned, licence-checked dependencies.

#319 named the `ollama` package. This design records why the runner uses `httpx2` instead (D1), as the owner decided
on 2026-11-17.

This change is built on #437 (`host-robustness`), which changes how runners write their output. It doesn't touch
`client.py`. The pull request opens only after #437 merges.

## Goals / Non-Goals

**Goals:**

- `client.py` sends and reads through `httpx2`, and keeps its interface and failure classes. Above it, nothing
  changes.
- Every behaviour the ollama-runner spec promises still holds, shown first by tests written against today's client,
  then by the existing fixtures, conformance and host tests, with no re-capture.
- The runner is `troupe-run[ollama]`, with the repository's extra, licence and install checks passing.
- #333's guarantees each have a test that would fail on the library's default.

**Non-Goals:**

- Any change to what the runner sends or does with an answer: the request body, the tools, the loop, retries,
  compaction, events and the transcript all stay as they are.
- The `ollama` package (D1).
- Connection reuse between requests. Each request still opens its own connection, as today (D3).

## Decisions

### D1. `httpx2`, not the `ollama` package

A probe of `ollama` 0.6.3, its latest release (2026-09-29), from its source and models (#332,
issuecomment-6947159287), found its public API can't keep the spec:

- `chat()` takes a fixed set of arguments, and its request model ignores unknown fields, so it can't send
  `truncate: false` or `shift: false`. Without them Ollama cuts an over-long conversation silently ("A run never
  carries on past its context window"). GitHub's main branch is the same.
- Its `Tool` model keeps only `type`, `items`, `required`, `properties` and four fields per property. That drops the
  SDK's `additionalProperties: false` and every `minimum` ("Every request offers the SDK's tools").
- Its `ChatResponse` drops `prompt_eval_cached_count` (the result's `cacheReadTokens`) and each tool call's `id` and
  `function.index`. It raises a validation error on `arguments` sent as a JSON string, which today reaches the SDK's
  tool runner as text.
- It has no `/api/version` call, no cap on a line's length, and timeouts only per client, not per call.
- By default it follows redirects and sends `OLLAMA_API_KEY` from the environment as a bearer token.

**Alternatives** (put to the owner on 2026-11-17):

- the package's client with the runner's own body through its private `_client`: every behaviour held, but it
  relied on a private attribute;
- its public `chat()`: it loses everything above, and the spec would have to change;
- the standard library until upstream catches up.

The owner chose a maintained HTTP library directly. It's what `ollama` itself sends through, and it lets the runner
send its exact bytes. #332's title and body now say so.

**Which HTTP library: `httpx2`, not `httpx`.** The Anthropic runner (through `anthropic`) and the OpenAI runner's move
onto `openai` (#331) are both built on `httpx2`, pydantic's maintained fork of `httpx`, which troupe already locks at
2.16.0. With `httpx` 0.28.1, `troupe-run[all]` would ship two HTTP stacks. `httpx2` has everything this design needs,
with the same API: `follow_redirects`, `trust_env`, `Limits`, `Timeout`, `iter_raw`, custom transports, and
`httpcore2.ConnectionPool(network_backend=…)`. The cancel probes (D4) gave the same results on it, both waking within
1.0 s. It also brings no `certifi` (D2). #331's session found the shared stack on 2026-11-17, and the owner's
decision ("a maintained HTTP library directly") covers `httpx2`. `httpx` 0.28.1 was released in December 2024, with
nothing since.

### D2. The dependencies: `httpx2` and `httpcore2`, pinned, in one module

The plugin depends on `troupe-plugin-sdk`, `httpx2==2.16.0` and `httpcore2==2.16.0`, the versions the lock already holds for the
Anthropic runner. `httpcore2` is named directly because the runner uses its public `ConnectionPool` and
`NetworkBackend` (D4). Their dependencies are `h11` (MIT), `anyio` (MIT), `idna` (BSD-3-Clause) and `truststore`
(MIT), all on `scripts/licences.toml`'s permissive tier, all pure Python, and all already locked. Both declare
`License-Expression: BSD-3-Clause`. No weak-copyleft package comes in: `httpx2` uses `truststore`, not `certifi`.

Only `client.py` imports `httpx2` or `httpcore2`. An import-linter contract pins that, as the Anthropic runner's seam
contract does. `client.py` keeps its interface and its failure classes, so `conversation.py`, `runner.py` and their
tests don't change.

**Alternatives:** `requests` (it reads `.netrc` and the environment by default, and has no streaming line limit of its
own either) and `urllib3` (lower level, and not the library #319 pointed at).

### D3. The client decides nothing for itself

`Client` builds one `httpx2.Client` for the run with:

- `follow_redirects=False`, said explicitly though it's `httpx2`'s default. A 3xx is a status like any other: from
  the chat request it's an `EngineError`, which ends the run with reason `other`, naming the status (`Ollama
  answered status 307`), unretried; from the preflight it's `ollama.unreachable`. That is today's behaviour, since `http.client` never
  followed one either, now pinned by a test.
- `trust_env=False`. `httpx2` otherwise reads `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`,
  `SSL_CERT_DIR` and `NETRC`, and sends a `.netrc` login as Basic auth. The runner sends no credential (spec: "A
  runtime with a credential is refused"), and today's client reads none of these. core already starts the runner
  with no variables (`interim.RUNNERS["ollama"].environment == ()`), but the runner shouldn't rely on that, since a
  person or another host can start it directly.
- **TLS:** for an `https` endpoint, an `ssl.create_default_context()`, the context `http.client` uses today, rather
  than `httpx2`'s default (`truststore`'s), so which certificates are trusted doesn't change with this move. Moving to
  the operating system's own store through `truststore` would be a change of its own.
- **Headers:** only `Content-Type: application/json` on a body, and `Accept-Encoding: identity`, so every answer line
  is the bytes Ollama sent (D5). `httpx2`'s `User-Agent` stays, and isn't recorded.
- **Connections:** no keep-alive (`max_keepalive_connections=0`), so each request has its own connection, as today,
  and `close` shuts down exactly the request in flight.
- **Retries:** none in `httpx2` or `httpcore2` (`retries=0`, their default). `conversation.py` keeps its own loop
  (`RETRY_MAX_ATTEMPTS`, `RETRY_DELAY_SECONDS`).

### D4. Cancel: a recorded socket, shut down from another thread

Today `close` shuts down the socket in flight, which wakes the blocked read on Linux, macOS and Windows, and the worker
then ends with `StoppedError`. Two probes (2026-11-17, macOS, from the scratchpad) tested the same with `httpx2`:

- **Closing the `httpx2.Client` from another thread** while a request waits for response headers (Ollama sends
  none while it loads a model) closed the connection, which the server saw. But it **didn't wake the read**, which
  stayed blocked until its timeout.
- **Shutting down the socket** woke the read within 1.0 s, both while waiting for headers and part-way through a
  stream, with `RemoteProtocolError`. The server saw the connection closed.

So `Client` needs the socket before the response exists. It gets it through `httpcore2`'s public extension points.
`client.py` has a small `httpx2.BaseTransport` over an `httpcore2.ConnectionPool`, built with the runner's SSL context,
no keep-alive and a `network_backend` that wraps `httpcore2.SyncBackend` and records each socket it connects. `close`
sets the closed flag, then shuts down every recorded socket that's still open. The transport mirrors
`httpx2.HTTPTransport.handle_request`, about 30 lines, and maps `httpcore2`'s exceptions to `httpx2`'s public ones
(`ConnectError`, `ReadTimeout`, `RemoteProtocolError` and so on) by name, so the rest of `client.py` catches
`httpx2` exceptions only.

The probe that replaced `HTTPTransport`'s private `_pool` worked too, but used a private attribute. The transport above
uses only documented API: custom transports are part of `httpx2`'s API, and `network_backend` is part of `httpcore2`'s.

The runner's exit path doesn't change. After `close`, the main thread joins the worker for `STOP_GRACE_SECONDS`, then
exits through `os._exit`, so even if a platform didn't wake the read, the process still exits within troupe's grace.
The cancel tests check that the worker stops before the grace runs out, on all three platforms in CI.

**Alternative:** abandon the request by ending the process, as the Anthropic runner does. It works, but waits out the
grace on every cancel and logs that the conversation didn't stop. Today's runner stops cleanly, and the spec's
scenarios say the request is closed.

### D5. Lines read as bytes, with today's cap

`chat` reads `response.iter_raw()` and splits lines itself, keeping at most `LINE_MAX_BYTES` of a line it hasn't
finished. A longer line is `RetryableError("network", …)`, as today. With `Accept-Encoding: identity`, the raw bytes
are Ollama's bytes, de-chunked. A response with any other `Content-Encoding` is refused as a network failure rather
than decoded, since the transcript records lines verbatim.

**Alternative:** `iter_lines()`. It decodes to text, which would mean re-encoding for the transcript (and changing
how a line that isn't UTF-8 is recorded), and it reads a line whole with no cap.

### D6. Timeouts from the runner's named settings

`httpx2` has no default the runner uses. Each call is given an `httpx2.Timeout` built from the runner's settings:

- **`chat`:** `STREAM_IDLE_TIMEOUT_SECONDS` for connect, read, write and pool, which is today's single socket timeout
  for the whole request. Going silent past it is `RetryableError("network", "Ollama sent nothing for 300s")`, as
  today.
- **`version` and `show`:** the time left of `PREFLIGHT_TIMEOUT_SECONDS`, the preflight's one shared deadline, as
  today.

No new setting is needed. The README's limits table already lists them, and gains a line saying they're the HTTP
client's timeouts.

### D7. Failures map to today's classes

| `httpx2` raises, or answers | Today's class |
|---|---|
| any status other than 200, from `chat` | `EngineError`, or `RetryableError("server", …)` for 500, 502, 503 and 504, with the error body (read up to `ERROR_BODY_MAX_BYTES`) |
| `TimeoutException` | `RetryableError("network", "Ollama sent nothing for …s")` |
| `RemoteProtocolError` while reading the body (a stream cut short) | the end of the lines, as `http.client` read it: the conversation, which knows an answer ends with a `done` line, retries it as `network` ("the connection ended before Ollama finished its answer"), as the `network-retries` fixture records |
| any other `TransportError` (`ConnectError`, `ReadError`, `RemoteProtocolError`, `WriteError`, …) | `RetryableError("network", …)` |
| `InvalidURL`, `UnsupportedProtocol`, or a host name the resolver refuses (`UnicodeError`) | `UnreachableError` in the preflight, as today's `ValueError` |
| any of these after `close` | `StoppedError` |
| `version` or `show` failing to connect, or answering the wrong shape | `UnreachableError`, as today |

### D8. Proving nothing changed: differential tests first

Before `client.py` changes, a new test module runs the same scripted exchanges through today's `Client` against the
fake endpoint (`tests/fake_ollama.py`), and records what each call returned or raised and what the fake received:

- each request's method, path and body bytes;
- the lines `chat` yielded;
- the failure class with its `reason`, `status` and body.

It covers a stream, every error status, a dropped connection, a stall, an over-long line, an `error` line, a
redirect, a closed client, and the preflight's calls. The expected values are written down as data, and the test
passes on main. The `httpx2` client then has to pass it unchanged, the error messages included except where a message
quotes the transport's own exception text, which the test matches by class and reason.

Then the existing suites run unchanged:

- `test_ollama_client.py`, `test_ollama_runner.py` and `test_ollama_fixtures.py`, which replays every fixture and
  checks exactly its events and transcript;
- the conformance suite;
- core's `test_ollama_host.py` and `test_perform_ollama.py`.

A fixture that has to be re-captured would mean the wire format changed, which this design says doesn't happen. If
one does, it's raised with the owner, not re-captured quietly.

New tests:

- a 307 to a second fake that records whether it was reached, from the chat request and from the preflight;
- `HTTP_PROXY`, `ALL_PROXY` and `NETRC` set in the runner's environment, with the fake checking it's reached directly
  and gets no `Authorization` header;
- cancel while a request waits for headers and while a stream is held open, each checking the fake sees the
  connection close and the worker stops before the grace runs out;
- an `https` endpoint whose handshake goes through the runner's own context: one that records and refuses
  `wrap_socket` sees it, and the preflight is unreachable. No certificate is needed, so no key is committed;
- `close` shutting down the socket TLS wraps a connection in, not only the first.

### D9. Shipping it

As `contributing/runners.md`'s "Runners with client libraries" table lists:

- the dependencies in the plugin's `pyproject.toml`, and `uv lock`. Every package is already locked, so the lockfile
  changes only in the plugin's own entry, checked package by package;
- the plugin moves from `troupe-run`'s `dependencies` to an `ollama` extra and `all`;
- `in_extra=True` on `interim.RUNNERS["ollama"]`, and core's tests that list which runners are extras;
- the install page's row for `troupe-run[ollama]`;
- the licence check, which passes with `scripts/licences.toml` unchanged: every package is on the permissive tier,
  and none is MPL-2.0.

The plugin hasn't released, so it's bare in the bundle, and the release-hold rule already covers it. The workspace's
`dev` group already installs every plugin, so core's tests that import `troupe_runner_ollama` keep working in
development. CI's install check installs `troupe-run[all]` and rehearses an audition on every runner, on every
platform and Python. That covers "installs on Linux, macOS and Windows for every supported Python".

Docs: `docs/opening-night/first-performance.md` says to install `troupe-run[ollama]` before `troupe init --audition
--runner ollama`, and `bring-your-own-agent.md`, `docs/prompt-book/cli.md` and the runner's README say the runner is an
extra. `contributing/runners.md`'s Ollama section says it uses `httpx2`, and why not `ollama`. No spec is added or
removed, and no Purpose changes, so infrastructure's `oob/troupe-spec-purposes.json` is untouched.

**#331 runs alongside.** It moves the OpenAI runner onto `openai`, and touches the same extras, the same interim test
(`test_only_the_anthropic_and_mistralrs_runners_come_as_extras`), the install page and the `cli` spec's init
scenarios. Whichever merges second rebases, carries the other's wording, and re-archives if the archive commit
conflicts.

## Risks / Trade-offs

- **The custom transport mirrors `httpx2`'s own** (D4), so a change in `httpx2` could leave the two apart. → Both
  libraries are pinned exactly, and a bump is its own change. The differential tests (D8) catch any change in what's
  sent or read, and the transport uses only documented extension points.
- **Shutting down a socket from another thread** has to wake the read on Windows, as it does today. → The cancel
  tests run in CI on all three platforms, and the process still exits within the grace if one didn't (D4).
- **Moving to an extra breaks `troupe init --audition --runner ollama`** for anyone who installed only the base
  package. → It's refused with `runner.not-installed` naming `troupe-run[ollama]`, as #333 built, and the
  first-performance guide installs the extra first. The runner hasn't released yet, so no installed version loses it.
- **More dependencies for a runner that had none.** → That's #319's decision. They come only with the extra, and are
  pure Python and licence-checked.
- **`trust_env=False` means no proxy**, though a person behind one might want it. → Today's client used none either,
  so nothing is lost. Supporting a proxy would be a feature of its own, with a named setting.
