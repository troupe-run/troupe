# Tasks

## 1. Check the runtime's hand-off before building on it (design D2)

- [x] 1.1 Confirm #278 has merged, and compare what its archived change gives a runner with D2's assumptions: the
  `runtime` in `run/start` (its endpoint, model and whether it has a credential), and the variable the credential's
  value arrives in. If anything differs, stop and update this change (`/opsx:update`) before going on. Verify: the
  comparison, with #278's spec lines, is in the first apply commit's message, or this change's artifacts are updated
  and `openspec validate openai-style-runner --strict` passes.

## 2. Scaffold the plugin and wire it into the workspace (design D1, D14)

- [x] 2.1 Create `plugins/runner-openai-chat/` as the Claude Code runner was made: `pyproject.toml`
  (`troupe-runner-openai-chat`, depending only on `troupe-plugin-sdk`, the script `troupe-runner-openai-chat`),
  `LICENSE` and a stub `README.md` (no `CHANGELOG.md`: release-please writes it at the first release, as for the SDK),
  and `src/troupe_runner_openai_chat/` with `__init__.py` (`NAME` `openai-chat`, `__version__`), `py.typed` and `defaults.py` holding D7's settings, the fixed instructions (D6) and
  the transcript's header list (D10). `__main__.py` lands with `runner.py` (5.1), which it imports. Verify: `uv sync` succeeds and `uv run python -c "import
  troupe_runner_openai_chat"` exits 0.
- [x] 2.2 Wire the member into the root `pyproject.toml` (workspace source and dev group, ruff, mypy and pytest paths,
  import-linter root packages, `plugins import nothing from troupe`, `plugins are independent of each other`, and a
  contract that only `troupe_runner_openai_chat.service` imports `urllib`, `http`, `socket` and `ssl`: top-level
  names, since import-linter refuses an external submodule), and into `release-please-config.json`,
  `.release-please-manifest.json`, `scripts/check-paths.toml` and the `troupe-run` bundle (bare until its first
  release), each as `runner-claude-code` and the SDK are. Verify: `uv run pytest scripts/tests/workspace` and `uv run lint-imports` pass, and a
  scratch module in the plugin importing `troupe` makes `lint-imports` fail, then is removed.

## 3. Options, schemas and the runtime (design D2, D7, D11)

- [x] 3.1 Add `schemas/options.schema.json` (closed: `maxTurns` and `maxTotalTokens`, positive integers) and
  `schemas/errors.schema.json` (`openai-chat.unknown-option`, `openai-chat.invalid-options`, `openai-chat.no-runtime`,
  `openai-chat.insecure-endpoint`, each with its details schema). Verify: a schema test passes the protocol's
  strictness check on both, validates the documented options, and refuses an unknown key and `maxTurns` 0.
- [ ] 3.2 Write `options.py` (parse and refuse, naming the option in `details.where`) and `runtime.py` (read the
  runtime from `run/start`, and the credential with the SDK's `runtime_credential`; refuse a missing runtime, a
  `run/start` and an environment that disagree about the credential (`openai-chat.credential-mismatch`), and a
  credential with an `http` endpoint to a non-loopback host). Verify: unit tests for each refusal in the spec's
  "options are closed", "service comes from the run's runtime", "read from TROUPE_RUNTIME_CREDENTIAL" and "never
  travels in the clear" scenarios pass, `127.0.0.1`, `::1` and
  `localhost` count as loopback, and `127.0.0.1.example.com` doesn't. That empty options give D7's defaults is
  checked here, by parsing them, and never by running a service on them.
- [ ] 3.3a Add `TEST_LIMITS` (`maxTurns` 5, `maxTotalTokens` 20,000) in one place in the plugin's tests (design D7).
  Every run a test starts uses it, unless the test sets limits of its own and says why: the runner tests, fixture
  replays, conformance, the perform tests and the live test. Verify: a test fails when any test helper starts a run
  whose options set neither limit. It's checked by planting one in a scratch test.
- [x] 3.3 Write the masking function (D11) that every outgoing event, record and error passes through. Verify: unit
  tests for the exact value and OpenAI's masked form (`sk-cana*********6789`), a credential under eight characters,
  and a property test that no output holds the credential whatever text surrounds it.

## 4. Talking to the service (design D3, D4, D8)

- [x] 4.1 Write the fake endpoint in the plugin's tests (D13): scripted statuses, headers, bodies and streams, pauses,
  cut-offs, held-open responses, and a record of every request and its headers. Verify: its own tests show each
  scripted behaviour reaching a plain `urllib` client.
- [x] 4.2 Write `service.py`: one request with the runtime's endpoint, model and credential, `stream` and
  `stream_options`, connect and stream timeouts, no redirects, proxies and TLS from the environment, and a handle the
  main thread can close. Verify: tests against the fake endpoint show the `Authorization` header only when there's a
  credential, a 307 not followed (the fake's second host gets nothing), and a held-open response closed from another
  thread within a second.
- [x] 4.3 Write the stream parser (D4): text, refusal, reasoning and tool-call deltas by index, the finish reason, and
  the final usage chunk, with a broken stream detected as the spec says. Verify: tests on a recorded stream, and a
  property test that any split of its bytes into reads gives the same response.
- [x] 4.4 Write the retry and failure classification (D8): each row of the table, `Retry-After` within the cap, and
  backoff. Verify: one test per row against the fake endpoint, each checking the `retry` events' attempt, reason,
  delay and message, or the `error` result's message, as the spec's scenarios state.

## 5. The tool loop and the run's events (design D5, D6, D9, D10)

- [ ] 5.1 Write `runner.py`: the handshake, `run/start` (options, runtime, declaration, `Tools`), `init` (name,
  version, `engine.name` `chat-completions`, `engine.model`, the tools, `effects` `checked`), and the threads and
  queue of D5. Verify: a test sees `init` first with those fields, and `run/start` refusals answered before any
  request reaches the fake endpoint.
- [x] 5.2 Write the loop: the system and user messages, tools offered, `turn` events, calls carried out in order with
  made-up ids where needed, tool messages, the `ok` result, refusals and unexpected finishes, the turn limit and the
  token budget. Verify: one test per scenario in the spec's loop requirements, against the fake endpoint, including a
  read-only actor's refused `Write` and arguments that aren't JSON.
- [x] 5.3 Sum usage and cost as D9 says, and warn when a response has no usage. Verify: the spec's usage and cost
  scenarios pass.
- [ ] 5.4 Send the transcript as D10 frames it, through the masking function. Verify: a test reads a run's transcript
  records back in order, finds no request header in any, and finds a 401's echoed key masked.
- [x] 5.5 Cut every summary to fit `eventMaxBytes` and `SUMMARY_MAX_BYTES`. Verify: the spec's 1 MiB reply scenario.
- [ ] 5.6 Handle `run/cancel`, end of input and `shutdown`. Verify: tests that cancel during a held-open response (the
  fake sees its connection closed, no `result` is sent, the runner exits within troupe's grace), close stdin mid-run,
  and shut down after a result, each passing on all three platforms in CI.

## 6. Fixtures, the capture tool and the credential scan (design D13)

- [ ] 6.1 Write `tools/capture_openai_chat.py` (records a run's responses against an endpoint, writes provenance, and
  scrubs the credential and the host's home path). Capture, without a working credential: a success with tool calls
  from a local server (Ollama or LM Studio, named in the provenance) and a rejected credential from OpenAI with an
  invalid key. Verify: each fixture's provenance says no working credential was used.
- [ ] 6.2 Ask the owner to capture the OpenAI success fixture with a working key. Build the rate-limit, server-error
  and refusal fixtures from OpenAI's documented shapes and the broken stream from a recorded success, each provenance
  naming its source. Verify: the provenance of each says recorded, derived or built.
- [ ] 6.3 Write each fixture's `expected.json` and the fixture tests: replay through the fake endpoint and match the
  events and outcome; the list of required fixtures; and the secret scan. Verify: the fixture tests pass, and a
  planted `sk-` string in a scratch copy of a fixture fails the scan, naming the fixture and line.
- [ ] 6.4 Write the canary test: every fixture and failure mode run with `sk-canary-0123456789`, every byte of the
  runner's stdout and stderr scanned for it and its masked forms. Verify: it passes, and fails when masking is
  switched off in a scratch edit.

## 7. troupe ships it (design D14)

- [ ] 7.1 Add `openai-chat` to `troupe.core.interim.RUNNERS` with D14's environment and `runtime="required"`, and
  update `runner.unknown`'s list. Verify: the `runs` delta's scenarios pass in `test_interim.py` and the perform tests
  (`HTTPS_PROXY` and `SSL_CERT_FILE` reach the runner, the key reaches it only as `TROUPE_RUNTIME_CREDENTIAL` and
  `OPENAI_API_KEY` doesn't, `codex` is refused naming all four runners, and an `openai-chat` actor naming no runtime
  is refused by config).
- [ ] 7.2 Run the conformance suite against the runner with a runtime naming the fake endpoint, as a test in
  `packages/troupe/tests/test_runner_conformance.py`. Verify: every check passes.
- [ ] 7.3 Write a perform test that runs an `openai-chat` actor end to end against the fake endpoint in a worktree,
  writing a declared file. Verify: the outcome is `succeeded`, `troupe logs` shows its events, and `troupe diff` shows
  the file.
- [ ] 7.4 Add the runner to the `troupe-run` bundle's pins as `troupe-runner-claude-code` was added, respecting
  #262's check. Verify: `uv run pytest scripts/tests` passes, including the release config tests.

## 8. Docs

- [ ] 8.1 Write the plugin's `README.md` (what it is, options, runtimes, limits, failures, transcript framing, how to
  capture fixtures and run the live test). Add its row to `plugins/README.md`, and a "Mapping an engine: Chat
  Completions" section to `contributing/runners.md` with D8's and D10's tables. Verify: a README test, as the Claude
  Code runner has, checks the options and error codes it lists match the published schemas.
- [ ] 8.2 Add the runner to the user docs where runners are chosen (`docs/prompt-book/config-schema.md` and the
  first-performance or bring-your-own-agent page), with an actor and runtime example. The example sets
  `maxTurns` 5 and `maxTotalTokens` 20,000, and says to raise them once the actor behaves (design D7). Verify: `uv run
  scripts/check.py` passes, including the docs checks, and the example's `troupe config set` commands run in a
  scratch theatre.

## 9. The live test, and the contract's gaps

- [ ] 9.1 Write the live test (`TROUPE_LIVE_OPENAI_CHAT=1`, model pinned in the test, `TEST_LIMITS`). Run it against a local OpenAI-compatible server. Verify: skipped without the variable, saying how to
  run it; `succeeded` against the local server, with the output shown.
- [ ] 9.2 Ask the owner to run the live test against OpenAI. Verify: the owner's run ends `succeeded`, and its endpoint,
  model and token use are recorded in the PR.
- [ ] 9.3 For each gap in D12 that building confirmed, check #56's issues and pull requests for the same gap, then
  file it as its own issue (on the board, 0.2.0, naming this change and the runner's behaviour today), and list them
  in the PR. Verify: each is on the board (`gh issue view <n> --json projectItems`).

## 10. Integration

- [ ] 10.1 Run `uv run scripts/check.py`. Verify: it passes locally, and CI passes on Linux, macOS and Windows once
  the PR is marked ready.

## Workflow follow-up

- Record the new spec's Purpose in troupe-run/infrastructure's `oob/troupe-spec-purposes.json`, in a pull request that
  merges after this one.
- Act on Claude's review, archive on the branch, and hand the PR to the owner to merge.
- After the merge, comment on #162 with the PR and the archived change, close it, and check its card says Done.
