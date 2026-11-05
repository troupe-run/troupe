# Tasks

The change was first built for Chat Completions under the names `openai-chat` and `runner-openai-chat`, then moved to
the Responses API by #290 (owner, 2026-11-05). Ticked tasks below whose work carries over stay ticked, and group 6
moves them to the new names and API. Tasks whose Chat Completions version is built but replaced are unticked, with a
note; they're ticked again when their Responses version passes.

## 1. Check the runtime's hand-off before building on it (design D2)

- [x] 1.1 Confirm #278 has merged, and compare what its archived change gives a runner with D2's assumptions: the
  `runtime` in `run/start` (its endpoint, model and whether it has a credential), and the variable the credential's
  value arrives in. If anything differs, stop and update this change (`/opsx:update`) before going on. Verify: the
  comparison, with #278's spec lines, is in the first apply commit's message, or this change's artifacts are updated
  and `openspec validate openai-style-runner --strict` passes.

## 2. Scaffold the plugin and wire it into the workspace (design D1, D14)

- [x] 2.1 Create the plugin as the Claude Code runner was made: `pyproject.toml` (depending only on
  `troupe-plugin-sdk`), `LICENSE` and a stub `README.md` (no `CHANGELOG.md`: release-please writes it at the first
  release, as for the SDK), and the package with `__init__.py` (`NAME`, `__version__`), `py.typed` and `defaults.py`
  holding D7's settings, the fixed instructions (D6) and the transcript's header list (D10). `__main__.py` lands with
  `runner.py` (5.1), which it imports. Verify: `uv sync` succeeds and the package imports. (Built as
  `runner-openai-chat`; renamed in 6.1.)
- [x] 2.2 Wire the member into the root `pyproject.toml` (workspace source and dev group, ruff, mypy and pytest paths,
  import-linter root packages, `plugins import nothing from troupe`, `plugins are independent of each other`, the
  OS-modules contract, and a contract that only the plugin's `service` module imports `urllib`, `http`, `socket` and
  `ssl`: top-level names, since import-linter refuses an external submodule), and into `release-please-config.json`,
  `.release-please-manifest.json`, `scripts/check-paths.toml`, the changelog page and the `troupe-run` bundle (bare
  until its first release), each as the other runners are. Verify: `uv run pytest scripts/tests/workspace` and
  `uv run lint-imports` pass, and a scratch module in the plugin importing `troupe` makes `lint-imports` fail, then is
  removed. (Renamed in 6.1.)

## 3. Options, schemas and the runtime (design D2, D7, D11)

- [x] 3.1 Add `schemas/options.schema.json` (closed: `maxTurns` and `maxTotalTokens`, positive integers) and
  `schemas/errors.schema.json` (the unknown-option, invalid-options, no-runtime, insecure-endpoint and
  credential-mismatch codes, each with its details schema). Verify: a schema test passes the protocol's strictness
  check on both, validates the documented options, and refuses an unknown key and `maxTurns` 0. (Codes renamed to
  `openai.*` in 6.1.)
- [x] 3.2 Write `options.py` (parse and refuse, naming the option in `details.where`) and `runtime.py` (read the
  runtime from `run/start`, and the credential with the SDK's `runtime_credential`; refuse a missing runtime, a
  `run/start` and an environment that disagree about the credential, and a credential with an `http` endpoint to a
  non-loopback host). Verify: unit tests for each refusal in the spec's "options are closed", "service comes from the
  run's runtime", "read from TROUPE_RUNTIME_CREDENTIAL" and "never travels in the clear" scenarios pass, `127.0.0.1`,
  `::1` and `localhost` count as loopback, and `127.0.0.1.example.com` doesn't. That empty options give D7's defaults
  is checked here, by parsing them, and never by running a service on them.
- [x] 3.3a Add `TEST_LIMITS` (`maxTurns` 5, `maxTotalTokens` 20,000) in one place in the plugin's tests (design D7).
  Every run a test starts uses it, unless the test sets limits of its own and says why. Verify: a test fails when any
  test helper starts a run whose options set neither limit.
- [x] 3.3 Write the masking function (D11) that every outgoing event, record and error passes through. Verify: unit
  tests for the exact value and OpenAI's masked form (`sk-cana*********6789`), a credential under eight characters, an
  echo inside JSON text, and a property test that no output holds the credential whatever text surrounds it.

## 4. Talking to the service (design D3, D4, D8)

- [x] 4.1 Write the fake endpoint in the plugin's tests (D13): scripted statuses, headers, bodies and streams, pauses,
  cut-offs, held-open responses, raw byte chunks, and a record of every request and its headers. Verify: its own tests
  show each scripted behaviour reaching a plain `urllib` client.
- [x] 4.2 Write `service.py`: one request with the runtime's endpoint and credential, connect and stream timeouts, no
  redirects, proxies and TLS from the environment, and a call another thread can abort. Verify: tests against the fake
  endpoint show the `Authorization` header only when there's a credential, a 307 not followed (the fake's second host
  gets nothing), and a held-open response closed from another thread within a second. (Its path changes to
  `/responses` in 6.2.)
- [ ] 4.3 Write the stream reader (D4): server-sent events with `event:` lines and no `[DONE]`, the reply taken from
  the final event's response object (`response.completed`, `response.incomplete`, `response.failed`, or an `error`
  event), and a broken stream detected as the spec says. Verify: tests on the recorded OpenAI and Ollama streams, and a
  property test that any split of a recorded stream's bytes into reads gives the same reply. (Built for Chat
  Completions, deltas by index and `[DONE]`; replaced in 6.2.)
- [x] 4.4 Write the retry and failure classification for HTTP statuses (D8): each status row of the table,
  `Retry-After` within the cap, and backoff. Verify: one test per row against the fake endpoint, each checking the
  `retry` events' attempt, reason, delay and message, or the `error` result's message. (The 404 hint names the
  Responses API in 6.2.)

## 5. The tool loop and the run's events (design D5, D6, D9, D10)

- [ ] 5.1 Write `runner.py`: the handshake, `run/start` (options, runtime, declaration, `Tools`), `init` (name,
  version, `engine.name` `responses`, `engine.model`, the tools, `effects` `checked`), and the threads and write lock
  of D5. Verify: a test sees `init` first with those fields, and `run/start` refusals answered before any request
  reaches the fake endpoint. (Built with `engine.name` `chat-completions`; changed in 6.3.)
- [ ] 5.2 Write the loop (D6): `instructions` and the first `input`, the Responses function tools, `store: false` and
  `include`, `turn` events, calls carried out in order, the output items sent back unchanged with one
  `function_call_output` per call, the `ok` result, refusals, incomplete and failed responses and unknown statuses, a
  call without a `call_id`, the turn limit and the token budget. Verify: one test per scenario in the spec's loop
  requirements, against the fake endpoint, including a read-only actor's refused `Write`, arguments that aren't JSON,
  and reasoning sent back unchanged. (Built for Chat Completions messages; replaced in 6.3.)
- [ ] 5.3 Sum usage and cost as D9 says (cache reads and writes apart), and warn when a response has no usage. Verify:
  the spec's usage and cost scenarios pass. (Built for Chat Completions' `prompt_tokens`; replaced in 6.3.)
- [x] 5.4 Send the transcript as D10 frames it, through the masking function. Verify: a test reads a run's transcript
  records back in order, finds no request header in any, and finds a 401's echoed key masked.
- [x] 5.5 Cut every summary to fit `eventMaxBytes` and `SUMMARY_MAX_BYTES`. Verify: the spec's 1 MiB reply scenario.
- [ ] 5.6 Handle `run/cancel`, end of input and `shutdown`. Verify: tests that cancel during a held-open response (the
  fake sees its connection closed, no `result` is sent, the runner exits within troupe's grace), close stdin mid-run,
  and shut down after a result, each passing on all three platforms in CI.

## 6. Move to the Responses API and the new names (design D1, D4, D6, D9, D15)

- [x] 6.1 Rename the plugin in one commit: `git mv` `plugins/runner-openai-chat` to `plugins/runner-openai`, the
  package to `troupe-runner-openai` and the module to `troupe_runner_openai`, the runner's name to `openai`, its error
  codes to `openai.*` and its schemas' `$id`s, and everything that names them (the root `pyproject.toml` and its
  contracts, release-please's config and manifest, `scripts/check-paths.toml`, the bundle, the changelog page,
  `scripts/tests/workspace/test_plugin_imports.py`, core's stand-in, and the uncommitted core work of 8.1 to 8.3).
  Verify: a search for `openai-chat` and `openai_chat` finds nothing outside `openspec/`, and the full check passes.
- [ ] 6.2 Replace the stream reader and point requests at `/responses` (4.3): the fake endpoint's helpers build
  Responses streams (`event:` and `data:` lines, deltas, a final event with the response object), the 404 hint names
  the Responses API, and the recorded OpenAI and Ollama streams (D15, made on 2026-11-05) are tested against. Verify:
  4.3's verification passes, and tick 4.3.
- [ ] 6.3 Replace the loop's request and continuation, and the usage mapping (5.2, 5.3), and change `init`'s engine to
  `responses` (5.1). Verify: 5.1's, 5.2's and 5.3's verifications pass, and tick them.

## 7. Fixtures, the capture tool and the credential scan (design D13)

- [ ] 7.1 Write `tools/capture_openai.py` (records a run's responses against an endpoint, writes provenance, and
  scrubs the credential and the host's home path). Make the two recordings of D15 fixtures, with their provenance:
  OpenAI's two-turn run (`gpt-6-luna`, the owner's working key) and local Ollama's (no key). Capture a rejected
  credential from OpenAI with an invalid key. Verify: each fixture's provenance says which key was used, and none
  holds a credential.
- [ ] 7.2 Build the rate-limit, server-error, failed-response, incomplete-response and refusal fixtures from the
  recorded shapes and OpenAI's documented ones, and the broken stream from a recorded success, each provenance naming
  its source. Verify: the provenance of each says recorded, derived or built.
- [ ] 7.3 Write each fixture's `expected.json` and the fixture tests: replay through the fake endpoint and match the
  events and outcome; the list of required fixtures; and the secret scan. Verify: the fixture tests pass, and a
  planted `sk-` string in a scratch copy of a fixture fails the scan, naming the fixture and line.
- [ ] 7.4 Extend the canary test to every fixture: each run with `sk-canary-0123456789`, every byte of the runner's
  stdout and stderr scanned for it and its masked forms. Verify: it passes, and fails when masking is switched off in
  a scratch edit.

## 8. troupe ships it (design D14)

- [x] 8.1 Add `openai` to `troupe.core.interim.RUNNERS` with D14's environment and `runtime="required"`, and update
  every list of the runners troupe knows. Verify: the `runs` delta's scenarios pass in `test_interim.py` and the
  perform tests (`HTTPS_PROXY` and `SSL_CERT_FILE` reach the runner, the key reaches it only as
  `TROUPE_RUNTIME_CREDENTIAL` and `OPENAI_API_KEY` doesn't, `codex` is refused naming all four runners, and an
  `openai` actor naming no runtime is refused by config). (Built as `openai-chat`, uncommitted; renamed in 6.1.)
- [ ] 8.2 Let the conformance suite give a runner a runtime and its credential, and run it against the runner with a
  runtime naming the fake endpoint, as a test in `packages/troupe/tests/test_runner_conformance.py`. Verify: every
  check passes. (Built, uncommitted.)
- [ ] 8.3 Write a perform test that runs an `openai` actor end to end against the fake endpoint in a worktree,
  writing a declared file. Verify: the outcome is `succeeded`, `troupe logs` shows its events, and `troupe diff`
  shows the file. (Built for Chat Completions, uncommitted.)
- [x] 8.4 Add the OpenAI audition (D14, the `config` and `cli` deltas): `OPENAI_AUDITION_MODEL` (`gpt-6-luna`) in one
  place in `troupe.core.audition`, the actor with `runtime: openai`, the model, `maxTurns` 10, `maxTotalTokens`
  100,000, `effects.write: ["**"]`, `expect: []` and the character, and `init`'s note on `OPENAI_API_KEY` and cost.
  Verify: the `config` and `cli` deltas' scenarios pass, and the test that every runner troupe knows has a valid
  audition passes for `openai`.
- [ ] 8.5 Check the `troupe-run` bundle includes the runner, respecting #262's check. Verify: `uv run pytest
  scripts/tests` passes, including the release config tests.

## 9. Docs

- [ ] 9.1 Write the plugin's `README.md` (what it is, options, runtimes, limits, failures, transcript framing, how to
  capture fixtures and run the live test). Add its row to `plugins/README.md`, and a "Mapping an engine: the
  Responses API" section to `contributing/runners.md` with D8's and D10's tables. Verify: a README test, as the
  Claude Code runner has, checks the options and error codes it lists match the published schemas.
- [ ] 9.2 Add the runner to the user docs where runners are chosen (`docs/prompt-book/config-schema.md` and the
  first-performance or bring-your-own-agent page), with an actor and runtime example. The example sets `maxTurns` 5
  and `maxTotalTokens` 20,000, and says to raise them once the actor behaves (design D7). Verify: `uv run
  scripts/check.py` passes, including the docs checks, and the example's `troupe config set` commands run in a
  scratch theatre.

## 10. The live test, and the contract's gaps

- [ ] 10.1 Write the live test (`TROUPE_LIVE_OPENAI=1`, model pinned in the test, `TEST_LIMITS`). Run it against
  local Ollama's `/v1`. Verify: skipped without the variable, saying how to run it; `succeeded` against local Ollama,
  with the output shown.
- [ ] 10.2 Ask the owner to run the live test against OpenAI, and check D9's assumption that `input_tokens` includes
  cache writes. Verify: the owner's run ends `succeeded`, and its endpoint, model and token use are recorded in the PR.
- [ ] 10.3 For each gap in D12 that building confirmed, check #56's issues and pull requests for the same gap, then
  file it as its own issue (on the board, 0.2.0, naming this change and the runner's behaviour today), and list them
  in the PR. Verify: each is on the board (`gh issue view <n> --json projectItems`).

## 11. Integration

- [ ] 11.1 Run `uv run scripts/check.py`. Verify: it passes locally, and CI passes on Linux, macOS and Windows once
  the PR is marked ready.

## Workflow follow-up

- Record the new spec's Purpose in troupe-run/infrastructure's `oob/troupe-spec-purposes.json`, in a pull request that
  merges after this one.
- Act on Claude's review, archive on the branch, and hand the PR to the owner to merge.
- After the merge, comment on #162 with the PR and the archived change, close it, and check its card says Done.
