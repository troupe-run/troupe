## 1. Differential tests against today's client (design D8)

- [x] 1.1 Add `plugins/runner-ollama/tests/test_ollama_client_differential.py`, which runs scripted exchanges through
      `Client` against the fake endpoint and checks each call's result or failure (class, `reason`, `status`, body)
      and what the fake received (method, path, body bytes) against expected values written as data. Cover:
      - a streamed answer;
      - each of 400, 401, 403, 404, 500, 502, 503 and 504;
      - a dropped connection;
      - a stall past the idle timeout;
      - a line over `LINE_MAX_BYTES`;
      - an `error` line;
      - a 307 redirect;
      - a closed client;
      - `version` and `show`, including a 404 model and a wrong-shaped answer.
- [x] 1.2 Run it on today's `http.client` client and see every case pass; commit it before `client.py` changes.
- [x] 1.3 Add the guarantee tests that pass on today's client too:
      - a 307 to a second fake, from chat and from the preflight, which never reaches the second fake;
      - `HTTP_PROXY`, `ALL_PROXY` and `NETRC` set (with a `.netrc` login for the fake's host), with requests reaching
        the fake directly and carrying no `Authorization`;
      - cancel while waiting for headers and while a stream is held open, with the fake seeing the close and the
        worker stopping before `STOP_GRACE_SECONDS`.

## 2. The dependencies and the extra (design D2, D9)

- [x] 2.1 Add `httpx2==2.16.0` and `httpcore2==2.16.0` to `plugins/runner-ollama/pyproject.toml`, with the comment
      saying why (#319, #332, this design). Run `uv lock`, then check the lockfile package by package: every package is
      already locked, so only the plugin's own entry may change.
- [x] 2.2 Move `troupe-runner-ollama` from `troupe-run`'s `dependencies` to an `ollama` extra and to `all`. Set
      `in_extra=True` on `interim.RUNNERS["ollama"]`, with its comment. Update core's tests that list which runners
      are extras.
- [x] 2.3 Run `scripts/runner_licences.py` and the bundle check, and see both pass with `scripts/licences.toml`
      unchanged.
- [x] 2.4 Add an import-linter contract that only `troupe_runner_ollama.client` imports `httpx2` or `httpcore2`. See
      it fail on a stray import, then pass.

## 3. The client on httpx2 (design D3 to D7)

- [x] 3.1 Write the transport: an `httpx2.BaseTransport` over `httpcore2.ConnectionPool`, with:
      - the runner's `ssl.create_default_context()`;
      - `max_keepalive_connections=0` and `retries=0`;
      - a recording `network_backend`;
      - `httpcore2`'s exceptions mapped to `httpx2`'s.
- [x] 3.2 Rewrite `Client` on an `httpx2.Client` built with `follow_redirects=False`, `trust_env=False`, that transport
      and only the runner's headers (`Content-Type` on a body, `Accept-Encoding: identity`). Keep `version`, `show`,
      `chat`, `close`, `closed` and every failure class and message.
- [x] 3.3 Read `chat`'s answer with `iter_raw()`, splitting lines with the `LINE_MAX_BYTES` cap, and refuse a
      `Content-Encoding` other than identity as a network failure.
- [x] 3.4 Give each call its `httpx2.Timeout` from `STREAM_IDLE_TIMEOUT_SECONDS`, or the preflight's time left. Make
      `close` set the flag, then shut down every recorded socket that's still open.
- [x] 3.5 Add tests for TLS:
      - an `https` endpoint's handshake goes through the runner's own context: a context that records and refuses
        `wrap_socket` sees it, and the preflight is unreachable;
      - `close` shuts down the socket TLS wraps a connection in, not only the first.
- [x] 3.6 Run 1.1 and 1.3 unchanged on the new client and see every case pass. Then run the plugin's whole suite
      (`test_ollama_client.py`, `test_ollama_runner.py`, `test_ollama_fixtures.py` and the rest), unchanged, and see
      it pass with no fixture re-captured.

## 4. Specs, docs and the README (design D9)

- [x] 4.1 Update the plugin's README: install with `troupe-run[ollama]`, its HTTP client's settings (no redirects,
      proxies, `.netrc` or retries of its own; the system trust store), and the limits table saying the timeouts are
      the HTTP client's.
- [x] 4.2 Update the install page's extras list, `first-performance.md` (install the extra before the audition),
      `bring-your-own-agent.md`, `docs/prompt-book/cli.md` if it says how to get the runner, and
      `contributing/runners.md`'s "Mapping an engine: Ollama" (`httpx2`, and why not `ollama`). Run the docs check.
- [x] 4.3 Add tests for the `cli` scenarios: `troupe init --audition --runner ollama` refused with
      `runner.not-installed` naming `troupe-run[ollama]` when the plugin isn't importable, and the audition notes
      naming the extra when it is.
- [x] 4.4 Add a test for the `ollama-runner` spec's dependency and extra scenarios: the plugin's dependencies and
      `troupe-run`'s extras, as read from their `pyproject.toml` files.

## 5. Verification

- [x] 5.1 Check `uptime`, and with the 1-minute load under ~40, run `uv run scripts/check.py`, with its output to a
      scratch file, and see it pass.
- [x] 5.2 Run the conformance suite and core's Ollama host tests (`test_ollama_host.py`, `test_perform_ollama.py`,
      `test_runner_conformance.py`), and see them pass.
- [x] 5.3 With a local Ollama available, run `TROUPE_LIVE_OLLAMA=1` for the live test. Otherwise say it wasn't run.
- [x] 5.4 `openspec validate ollama-library --strict`.
