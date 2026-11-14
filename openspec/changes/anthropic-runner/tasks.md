# Tasks

The runner is built on the `anthropic` package (decisions troupe#319 and troupe#412) and ships as the optional extra
`troupe-run[anthropic]` (troupe#333's mechanism, already on main). LM Studio is the local engine it's proved against
(design D12). Claude's API fixtures and live run need the owner's key: the agent sends the owner a script, and never
asks for the key.

## 1. Probe before building on it (design D12)

- [x] 1.1 Probe tool calls, stream events, the context limit, the output limit and usage on LM Studio and Ollama
  through `anthropic` 2.8.0, from the scratchpad, and read the library's redirect, retry and credential behaviour from
  its source. Verify: the findings are on troupe#415 (issuecomment-6865689324), each naming the engine, its version,
  the library's version and the model.
- [x] 1.2 Probe what's left, each before the code that depends on it: cancel mid-stream by closing the stream and the
  client from another thread (D9); a 3xx through a client built with `follow_redirects=False` (D10); `max_tokens`
  above LM Studio's loaded window; LM Studio with "Require Authentication" on and a Bearer token (ask the owner to turn
  it on, or skip and say so); and that the client subclass with `Authorization` omitted reads no `ANTHROPIC_*` variable
  or profile (D4). Verify: findings added to troupe#415, and where one differs from the design or the spec, the
  artifacts are updated with `/opsx:update` and `openspec validate anthropic-runner --strict` passes.
  Done: findings on troupe#415 (issuecomment-6866687695); D4, D9 and D12 updated (cancel ends the process, the
  runner clears `ANTHROPIC_*` from its environment); LM Studio's authentication not probed (needs the owner), said in
  D12.

## 2. Record the new spec's Purpose in infrastructure (design D15)

- [ ] 2.1 Raise an infrastructure issue on the board and open its pull request adding `anthropic-runner`'s Purpose
  (without its `Capability:` line, whitespace collapsed) to `oob/troupe-spec-purposes.json`, following its
  `oob/README.md`, and check `cap:actor-runners`' description still covers it. Verify: the recorded Purpose matches
  this branch's spec verbatim, its checks pass, and this change's pull request says it merges first and links it.

## 3. The built-in runtime (design D3)

- [x] 3.1 Add `defaults.RUNTIMES["anthropic"] = {"endpoint": "https://api.anthropic.com", "credential": {"env":
  "ANTHROPIC_API_KEY"}}`, and update the tests that list the built-ins. Verify: a test for the runtimes delta's
  "Claude's API is a built-in", and core's suite passes.
- [x] 3.2 Update `docs/stagecraft/runtimes.md`: the `anthropic` built-in, and a runtime of your own for a local engine
  serving the Messages API (LM Studio's root, with the two `troupe config set` lines: the runtime's endpoint and the
  actor's runtime), not the built-in `lm-studio` runtime, which #413 removes (owner, 2026-11-14). Verify: the docs page
  tests pass, and the page shows both lines.

## 4. Check the library's dependencies before locking them (design D15)

- [x] 4.1 Check `anthropic` 2.8.0 and every package it pulls in against `scripts/licences.toml` and for wheels or pure
  Python on Linux, macOS and Windows, Python 3.12 to 3.15 (`pydantic-core` 2.50.4 and `jiter` 0.19.0 have cp312 to
  cp315 wheels on all three, checked 2026-11-14). If any fails, stop and raise it with the owner. Verify: the list of
  packages, versions, licences and wheels is in the commit message that adds the dependency.

## 5. Scaffold the plugin and wire it into the workspace (design D1, D15)

- [x] 5.1 Create `plugins/runner-anthropic` as the LM Studio runner was made: `pyproject.toml` (depending on
  `troupe-plugin-sdk` and `anthropic==2.8.0`), `LICENSE`, a stub `README.md`, and the package with `__init__.py`
  (`NAME`, `__version__`), `__main__.py`, `py.typed` and `defaults.py` holding D5's and D10's settings and the fixed
  instructions. Verify: `uv lock` pins `anthropic` and its dependencies, `uv sync` succeeds, and the package imports.
- [x] 5.2 Wire it in: the root `pyproject.toml` (workspace source and dev group, ruff, mypy and pytest paths,
  import-linter root packages, `plugins import nothing from troupe`, `plugins are independent of each other`, the
  OS-modules contract, and a seam contract that only `service.py` imports `anthropic` and `httpx2`),
  `scripts/check.py`'s scopes (`runner_anthropic`), `scripts/check-paths.toml`, `scripts/licences.toml`,
  `release-please-config.json`, `.release-please-manifest.json` and the changelog page. Verify: `uv run pytest
  scripts/tests` and `uv run lint-imports` pass, a scratch module importing `anthropic` outside `service.py` makes
  `lint-imports` fail and is then removed, and a test asserts that a change under `plugins/runner-anthropic/src/`
  selects `--scope runner_anthropic` (quality-check delta).

## 6. Options, schemas, the runtime and the credential (design D3, D4, D5, D6)

- [x] 6.1 Add `schemas/options.schema.json` (closed: `maxTurns`, `maxTotalTokens`, `maxOutputTokens`,
  `contextWindow`) and `schemas/errors.schema.json` (every `anthropic.*` code the spec names, each with its details).
  Verify: a schema test passes the protocol's strictness check on both and validates the documented options.
- [x] 6.2 Write `options.py`. Verify: tests for "The runner's options are closed" and "Each request asks for the run's
  output limit", and a property test that the parser and the published schema accept and refuse the same objects.
- [x] 6.3 Write `runtime.py`: require a runtime, refuse an endpoint ending `/v1` or with a query or fragment (never
  repeating user info), read and check the credential, and refuse a credential over plain `http` off loopback. Verify:
  tests for each scenario under "The service comes from the run's runtime", "The runtime's endpoint is the API's base
  URL", "The credential is read from TROUPE_RUNTIME_CREDENTIAL" and "A credential never travels in the clear", each
  checking nothing reached the fake endpoint and no output holds the credential.

## 7. The fake endpoint and the capture tool (design D12, D14)

- [x] 7.1 Write `tests/fake_messages.py`: answers `/v1/messages` with scripted or recorded SSE streams and error
  bodies, can redirect, drop the connection, stall, send an `error` event, answer JSON, or hold a stream open, and
  records each request with its headers. Verify: its own tests drive `anthropic` 2.8.0 through a recorded tool loop
  against it and check what it recorded.
- [x] 7.2 Write `tools/capture_anthropic.py`: drives the library against a runtime from the environment with a
  recording transport, writes each request's parameters and streamed events with provenance, scrubs credentials,
  request ids and host paths, and never writes the key. Capture the LM Studio fixtures with it: a tool loop, the
  first-prompt refusal (`500`), a conversation LM Studio cut, and the output limit; and the rejected-credential fixture
  against Claude's API with a deliberately invalid key. Verify: the fixtures are in `fixtures/`, and a test checks that
  no fixture holds a credential pattern or a path under the capturing host's home directory.
- [x] 7.3 Send the orchestrator, for the owner, the exact command that captures the Claude fixtures (a tool loop and a
  context refusal from a long prompt, plus a refusal if one can be had), with the key read from `ANTHROPIC_API_KEY` in
  the owner's own environment, the model, and the most it can cost. Verify: once the owner has run it, the fixtures are
  committed with provenance naming the owner's capture; until then the pull request says they're pending.
  Done: the owner's first run had no key in its shell and recorded two 401s, which were deleted, and the tool now
  refuses to record without a key from a hosted service; the second run (2026-11-14) recorded `claude-tool-loop` (two
  200s, so the key works as `Authorization: Bearer`) and `claude-context-refused` ("prompt is too long: 2100077 tokens
  > 1000000 maximum").

## 8. The service seam (design D1, D4, D10)

- [x] 8.1 Write `service.py`, the only module that imports `anthropic`: build the `httpx2` client with
  `follow_redirects=False`, the named timeouts and no environment beyond proxies and CA files; build the library's
  client as a subclass with `max_retries=0`, `base_url`, the credential as `api_key` or `Authorization` omitted,
  OpenTelemetry off, and the library's loggers kept off standard output; stream one request, giving the runner each
  event, the accumulated message, or one of a closed set of failures (status with type, message and headers; network;
  timeout; broken stream; unreadable). Verify: tests for "The library finds nothing of its own", "The credential goes
  only in the Authorization header", "Redirects are never followed", "The library's own logging stays out of the run's
  output" and "Every timeout the library applies is one of the runner's named settings", each failing on the library's
  default.

## 9. The run: tools, replies, limits, failures and stopping (design D2, D5, D7, D9, D10)

- [x] 9.1 Write the conversation and request building: `system` from the fixed instructions and the character, the
  direction as the first message, the SDK's tools, `max_tokens`, each reply's content appended unchanged, and one user
  message of `tool_result`s per reply. Verify: tests for "The character is the system prompt and the direction the
  first message", "The model is offered the SDK's tools" and "Tool calls are carried out in order and answered in the
  next request".
- [x] 9.2 Write the loop (`loop.py`): calls through the SDK's `Tools`, turns before calls, stop reasons mapped, usage
  summed, the turn limit and budget, `served_model`, cost estimated from the price, summaries cut. Verify: tests for
  each scenario under "The runner applies the effects by checking each call", "A malformed tool call is answered, not
  fatal", "A finished reply without tool calls ends the run", "Assistant text is reported as turns", "A reply that
  stops for another reason ends the run with an error", "Every run has a turn limit and a token budget", "Usage is
  summed into the result", "Cost is estimated from troupe's price", "A reply's model, when not the runtime's, is a
  served_model event" and "Summaries fit below the event limit".
- [x] 9.3 Write the failures and retries: one table from status and error type to retry or reason, `Retry-After` and
  `retry-after-ms` within the cap, stream `error` events, broken and silent streams, replies that can't be read, and
  the credential masked in every message. Verify: tests for each scenario under "Transient failures are retried by the
  runner, not the library", "A rate limit's Retry-After is honoured within a named cap", "Failures retrying can't fix
  end the run at once", "An endpoint or service that can't serve the run is a configuration failure", "A broken stream
  is retried as a network failure", "A reply the runner can't read ends the run", "The runner's unexpected failure is a
  runner failure" and "A service's echo of the credential is masked".
- [x] 9.4 Write the runner (`runner.py`): handshake, the pre-run check before acknowledging, `init`, the worker
  thread, and cancel, end of input and shutdown closing the stream and the client from the main thread and exiting
  within the named grace. Verify: tests for "The Anthropic runner is a self-contained plugin" and each scenario under
  "Cancel and end of input stop the request in flight", on all three platforms.

## 10. The context guard and compaction (design D8, D11)

- [x] 10.1 Write `context.py`: the table of context signals (each entry naming its engine and the fixture that pins
  it), the shrinking-prompt rule and the `contextWindow` rule, each ending a run told `fail` with `context-length`
  without acting on a reply made from a cut conversation. Verify: tests for each scenario under "A context-length
  refusal ends the run with context-length", "A reply made from a cut conversation is never acted on" and "A run stops
  before the context window the person named", the LM Studio fixtures among them, and a property test that a prompt
  that never shrinks never trips the rule.
- [x] 10.2 Write compaction for a run told `compact`, through the SDK's `compaction` helpers. Verify: tests for each
  scenario under "A run told compact compacts its conversation and asks again", including that every assistant message
  is sent back byte for byte.

## 11. The transcript (design D11)

- [x] 11.1 Send `sent`, `received` and `note` records as the spec says, before the events they lead to, with the kept
  headers named in one place. Verify: tests for "The transcript is what the library exposes", including that no record
  holds a request header and that a field the runner doesn't read survives into the record.

## 12. Fixtures, conformance and the live tests (design D12, D14)

- [x] 12.1 Build the fixtures that can't be recorded on demand (a rate limit, an overload, a server error, a broken
  stream, a refusal, a stream `error` event) from the API's documented shapes and the recorded ones, marked as built
  or derived, and give every fixture its expected events and outcome. Verify: a test replays every fixture through the
  fake endpoint and checks its events, transcript and outcome, and "The fixtures there are" holds (Claude's pending
  until 7.3).
- [x] 12.2 Run the conformance suite against the runner on a runtime naming the fake endpoint. Verify: the conformance
  test passes.
- [ ] 12.3 Write the live tests, `TROUPE_LIVE_ANTHROPIC=1` (Claude's API, the audition model, low limits) and
  `TROUPE_LIVE_ANTHROPIC_LOCAL=1` (a runtime and model from the environment). Verify: without the variables both are
  skipped, naming them; the local one passes against the owner's LM Studio (the agent runs it, since it costs
  nothing), and the owner runs the Claude one with `!` (sent through the orchestrator with 7.3), its output quoted in
  the pull request.

## 13. Ship it in troupe (design D3, D15)

- [x] 13.1 Join #333's extras, as `contributing/runners.md` "Runners with client libraries" lists: `anthropic =
  ["troupe-runner-anthropic"]` and the same in `all` in `troupe-run`'s optional dependencies, never in `dependencies`;
  `interim.RUNNERS["anthropic"]` with `runtime="required"`, `in_extra=True`, the proxy environment and
  `fit=RuntimeFit(version=True, built_in="anthropic")` (and `endpoint-version`, owner 2026-11-14); the bundle's exclude-paths as `scripts/release_config.py` says; and a row in
  `docs/opening-night/install.md`'s extras table. Verify: `uv sync --locked`, the bundle, release configuration,
  install docs and licence checks pass; core tests show an `anthropic` actor on a runtime of your own at
  `http://127.0.0.1:1234` accepted, an `anthropic` actor with no runtime refused naming
  `actors.<name>.runtime`, the base install refusing it with `runner.not-installed` naming `troupe-run[anthropic]`, and
  perform passing the runner no `ANTHROPIC_*` variable.
- [x] 13.2 Add the audition: `_anthropic` in `core/audition.py`, `ANTHROPIC_AUDITION_MODEL = "claude-haiku-5-5"` in
  one place, `maxTurns` 10 and `maxTotalTokens` 100,000, and the note `init` prints. Verify: tests for the cli delta's
  scenarios and the config delta's.
- [x] 13.3 Write the plugin's README (the extra, the `anthropic` runtime and a local engine's runtime of your own with its two
  `troupe config set` lines, the options and their defaults, the
  named timeouts, the context guard and what it can't catch, what the transcript keeps and loses, reasoning in a local
  model's text, and the gaps from D13), and update `plugins/README.md`, `contributing/runners.md` and
  `docs/stagecraft/bring-your-own-agent.md` where they list runners. Verify: the README test passes, and every page
  that lists runners names `anthropic`.

## 14. File the gaps (design D13)

- [x] 14.1 For each D13 candidate that building confirmed, check #279's, #319's and #412's issues and file it: troupe
  issues on the troupe roadmap board citing this change, and upstream reports linked from a troupe issue. Verify: each
  troupe issue shows the board in `gh issue view <n> --json projectItems`, and D13 lists its number or says why it
  wasn't filed.
  Done: troupe#418 (local engines cut a full context silently) and troupe#419 (LM Studio's `input_tokens` holds its
  cache reads), both Bugs on the board; not reported upstream (owner, 2026-11-14); `x-api-key` not filed (D13).

## 15. Verify the whole change

- [x] 15.1 Run `uv run scripts/check.py` (the full check, when the load is under 40), its output kept in a scratch
  file. Verify: it passes, and its summary line is quoted in the last commit's message or the pull request.
  Done: the commit guard's full check on b781e4f7, "check: all gates passed" (tests passed in 304.2s).
- [ ] 15.2 Open the pull request as a draft (`Closes #415`), act on the review of the last push, and mark it ready once
  the review is clean, the infrastructure Purpose pull request's checks pass, and the owner's Claude capture is in or
  the owner has said to go without it. Verify: `gh pr checks` shows every job passing on the head commit, on Linux,
  macOS and Windows.

## Workflow follow-up

- Archive on the branch (`/opsx:archive`) after the review is acted on, before the owner merges; if #413 merged first,
  carry its wording into this change's deltas.
- After the merge, check #415 is closed and its card Done, and comment on it with the pull request and the archived
  change.
