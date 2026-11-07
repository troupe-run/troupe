# Tasks

The runner is built on LM Studio's `lmstudio` package (decision troupe#319), not #302's MCP server, which is on hold.
It ships as an optional extra of `troupe-run`, which troupe#333 builds. Everything up to group 10 can be built before
#333 lands. Group 11's extra and its error wait for it, and this change's pull request isn't marked ready until #333
has merged.

## 1. Probe LM Studio through the library before building on it (design D12)

- [ ] 1.1 With the owner's LM Studio server running (the owner starts it with `lms server start`) and a small
  tool-capable model, run a throwaway probe through `lmstudio` 1.5.0 from the scratchpad, never committed. Record each
  item D12 lists: the least LM Studio version and any version report, authentication on, a two-round `act()` with the
  order of calls, text and round completion, each round's stats, unknown, missing and extra arguments and an unknown
  tool, the turn limit's last round, a token budget spent mid-run, `contextLength` against a loaded model and load
  progress, cancel mid-prediction and client close, and whether the process exits promptly after `close()`. Verify:
  the findings are in a comment on troupe#291, each naming LM Studio's version, the library's version and the model.
- [ ] 1.2 Compare the findings with design D4–D10 and the `lm-studio-runner` spec. Where one differs, update the
  artifacts with `/opsx:update` before any code depends on them, and pick the audition model (D15). Verify: the
  artifacts match the findings, and `openspec validate lmstudio-runner --strict` passes.

## 2. Record the new spec's Purpose in infrastructure (design D15)

- [ ] 2.1 Add `lm-studio-runner`'s Purpose (without its `Capability:` line) to troupe-run/infrastructure's
  `oob/troupe-spec-purposes.json`, following its `oob/README.md`, in a pull request of its own that cites troupe#291.
  Verify: that pull request's checks pass and it has merged (the owner merges) before this change's pull request is
  marked ready.

## 3. The built-in runtime (design D3)

- [ ] 3.1 Change `defaults.RUNTIMES["lm-studio"]` to `{"endpoint": "http://127.0.0.1:1234"}`, and update
  `test_runtime_defaults.py` and any test that reads the old value. Verify: a test asserts the new endpoint, and
  `config get --resolved runtimes.lm-studio` shows it from `default` (the runtimes delta's new scenario), passing in
  core's suite.
- [ ] 3.2 Update `docs/stagecraft/runtimes.md`: the built-in's endpoint, and how to put the OpenAI runner on LM Studio
  with a runtime of your own at `/v1`. Verify: the docs page tests (user-docs contract) pass, and the page shows the
  `troupe config set` lines for that runtime.

## 4. Check the library's dependencies before locking them (design D15)

- [ ] 4.1 Check that `lmstudio` 1.5.0 and every package it pulls in pass #333's licence check, which walks `uv.lock`
  against an allowlist (Apache-2.0, MIT, BSD-2-Clause, BSD-3-Clause, ISC, PSF-2.0), and have wheels for, or build on,
  Linux, macOS and Windows for Python 3.12 to 3.15 (msgspec is compiled). httpx pulls in `certifi`, which is MPL-2.0 and
  isn't on that allowlist, and none of these packages is in `uv.lock` yet. If one fails either check, stop and raise it
  with the owner. Verify: the list of packages, versions, licences and the wheels found is in the commit message that
  adds the dependency, or the owner's answer is.

## 5. Scaffold the plugin and wire it into the workspace (design D2, D15)

- [ ] 5.1 Create `plugins/runner-lm-studio` as the OpenAI runner was made: `pyproject.toml` (depending on
  `troupe-plugin-sdk` and `lmstudio==1.5.0`), `LICENSE`, a stub `README.md`, and the package with `__init__.py`
  (`NAME`, `__version__`), `py.typed` and `defaults.py` holding D5's settings and the fixed instructions (D7). Verify:
  `uv lock` pins `lmstudio` and its dependencies, `uv sync` succeeds, and the package imports.
- [ ] 5.2 Wire it into the root `pyproject.toml` (workspace source and dev group, ruff, mypy and pytest paths,
  import-linter root packages, `plugins import nothing from troupe`, `plugins are independent of each other`, the
  OS-modules contract, and a seam contract that only the plugin's engine module imports `lmstudio`), `scripts/check.py`'s
  scopes (`runner_lm_studio`), `scripts/check-paths.toml`, `release-please-config.json`, `.release-please-manifest.json`
  and the changelog page. Leave it out of `troupe-run`'s base dependencies (group 11). Verify: `uv run pytest
  scripts/tests` and `uv run lint-imports` pass, a scratch module that imports `troupe` makes `lint-imports` fail and is
  then removed, and a test asserts that a change under `plugins/runner-lm-studio/src/` selects
  `--scope runner_lm_studio` (quality-check delta).

## 6. Options, schemas and the runtime (design D3, D4, D5)

- [ ] 6.1 Add `schemas/options.schema.json` (closed: `maxTurns`, `maxTotalTokens`, `contextLength`, `temperature` 0
  to 1), `schemas/errors.schema.json` (every `lm-studio.*` code the spec names, each with its details schema), and
  `requirements.json` (from the probe). Verify: a schema test passes the protocol's strictness check on both and
  validates the documented options, and a test reads the published requirement.
- [ ] 6.2 Write `options.py`: parse and refuse, naming the option in `details.where`. Verify: tests for each
  "options are closed" scenario, and a property test that the parser and the published schema accept and refuse the
  same generated objects.
- [ ] 6.3 Write `runtime.py`: require a runtime, turn its endpoint into the library's host and port, refuse an `https`
  endpoint or one with a path, refuse a credential, and refuse a credential the environment holds that `run/start`
  doesn't mention. Verify: a test for each scenario under "The service comes from the run's runtime", "The runtime's
  endpoint is the library's host and port", "An endpoint the library can't use is refused" and "A runtime with a
  credential is refused", each checking nothing reached the fake endpoint and no output holds the credential.

## 7. The fake LM Studio endpoint and the capture tool (design D12, D14)

- [ ] 7.1 Write `tools/capture_lm_studio.py`: a recording proxy between `lmstudio` and a real LM Studio that writes a
  run's greeting and websocket exchange with provenance, scrubbing client passkeys and the host's paths. Capture the
  probe's recordable runs with it. Verify: a capture of a two-round run is in `fixtures/`, and a test checks that no
  fixture holds a passkey or a path under the capturing host's home directory.
- [ ] 7.2 Write `tests/fake_lm_studio.py`: answers the greeting and replays a recording's websocket exchange to the
  library, matching requests by method and channel and rewriting the ids and passkeys the library makes up. Its scripts
  can drop the connection, stall, redirect the greeting or slow a prediction, and it records what the library sent.
  Verify: its own tests drive `lmstudio` 1.5.0 through a recorded two-round run against it, and check what it recorded.

## 8. The pre-run check and the model (design D6)

- [ ] 8.1 Write the engine module (`engine.py`, the only one that imports `lmstudio`): open the client with the
  runtime's host and port, never the library's default ports, set the library's message timeout from the named
  setting, keep its loggers off standard output, and list the downloaded models. Verify: tests for "The runtime's
  endpoint is the library's host and port" (including an LM Studio on a default port that's never reached), "Redirects
  are never followed" and "The library's own logging stays out of the run's output".
- [ ] 8.2 Write the pre-run check: unreachable, the published requirement, model not found (with `lms get`), and model
  without tools. Verify: a test for each scenario under "The runner checks LM Studio before it acknowledges the run"
  and "The pre-run check finds a model that can call tools", each checking that no run is acknowledged.
- [ ] 8.3 Write the model load after `init`: load with the run's context length when it isn't loaded, with progress as
  `log` events, and report a loaded model's different length. Verify: tests for each scenario under "The model is
  loaded with the run's context length, and the length is reported".

## 9. The run: tools, rounds, limits and stopping (design D5, D7, D8, D9, D10, D11)

- [ ] 9.1 Write the tool definitions: each SDK tool as a `ToolFunctionDef` with typed, described parameters, and its
  implementation calling `Tools.run` with a made-up call id and checking the stop flag first. Verify: a test that the
  JSON schema the library builds matches the SDK's schema field by field ("The model is offered the SDK's tools"), and
  a test pinning that an unknown argument name is dropped by the library (D7).
- [ ] 9.2 Write `handle_invalid_tool_request`: answer with `Tools.run` on the raw arguments, so the model gets the SDK's
  error and the run reports the pair. Verify: tests for each scenario under "A call the library rejects is answered as
  troupe would answer it".
- [ ] 9.3 Write the runner (`runner.py`, `__main__.py`): handshake, the pre-run check before acknowledging, `init`, the
  chat, `act()` with the turn limit, text as turns at the first call and at round end, stats summed and the budget
  checked at each round's end, stop reasons mapped, and the library's exceptions mapped, all written under one lock.
  Verify: tests for each scenario under "The runner identifies itself as lm-studio", "The character is the system
  prompt and the direction the first message", "Each tool call is carried out by the SDK and checked against the
  effects", "Every run has a turn limit and a token budget", "Assistant text is reported as turns", "A round without a
  tool call ends the run", "The result carries the run's counts", "LM Studio's failures end the run as error results"
  and "Summaries fit below the event limit".
- [ ] 9.4 Write the retries: a failed or dropped connection retried with `retry` events within the named attempts,
  only while no tool call has run. Verify: tests for each scenario under "A connection is retried only before any tool
  call has run", including that one dropped connection gives exactly one `retry` event and that the fake endpoint saw
  no second chat after a call.
- [ ] 9.5 Write the transcript: the model's info, the chat and tools, each round's result and each tool message,
  serialised, each before the events it leads to. Verify: tests for "The transcript is what the library exposes".
- [ ] 9.6 Write cancel, end of input and shutdown: the stop flag under the lock, the prediction cancelled and the client
  closed (as the probe settled), and exit within the named grace even if the library's threads haven't finished.
  Verify: tests for each scenario under "Cancel and end of input stop the run at once", including a tool call asked for
  after cancel that isn't carried out, on all three platforms.

## 10. Fixtures, conformance and the live test (design D12, D14)

- [ ] 10.1 Build the fixtures that can't be recorded on demand (a dropped connection, a stall) from recorded shapes,
  marked as built, and give each fixture its expected events. Verify: a test replays every fixture through the fake
  endpoint and checks its events and transcript records.
- [ ] 10.2 Run the conformance suite against the runner on a runtime naming the fake endpoint. Verify: the conformance
  test passes.
- [ ] 10.3 Write the live test, `TROUPE_LIVE_LM_STUDIO=1`, with the runtime from the environment, a pinned model and
  low limits. Verify: without the variable it's skipped naming it, and with the owner's LM Studio it passes once (the
  owner runs it with `!`, and the output is quoted in the commit or the pull request).

## 11. Ship it in troupe (design D3, D15)

- [ ] 11.1 Once #333 (change `runner-extras`) has merged, join its extras as it lists for a library-backed runner:
  `lmstudio` in the plugin's dependencies, an `lm-studio` extra in `troupe-run` and the same entry in `all`,
  `in_extra=True` on the runner table's `lm-studio` entry (with `runtime="required"` and no environment), a row in the
  install page's list of extras, and the release-please exclusion while the plugin is bare. Coordinate details with the
  #333 session (`track-b-26-333-troupe-runner-extras`). Verify: the repo check passes (it fails when any of these is
  missing), core tests that an `lm-studio` actor with no runtime is refused naming `actors.<name>.runtime` and that one
  without the extra gets `runner.not-installed` naming `troupe-run[lm-studio]`, that perform starts the runner with no
  variable from the person's environment, and CI's install check, which rehearses every runner's audition, passes on
  Linux, macOS and Windows for every supported Python.
- [ ] 11.2 Add the audition: `_lm_studio` in `core/audition.py`, `LM_STUDIO_AUDITION_MODEL` in one place, `maxTurns` 10
  and `maxTotalTokens` 100,000, and the note `init` prints. Verify: tests for the cli delta's scenarios ("The LM Studio
  runner", and the unknown-runner error naming `lm-studio`) and the config delta's ("The LM Studio actor's file", "What
  init prints for it").
- [ ] 11.3 Write the plugin's README (the extra, "Require Authentication" off, plain `ws://`, the runtime, the options,
  what the transcript keeps and loses, and the gaps from D13), and update `plugins/README.md`, `contributing/runners.md`
  and `docs/stagecraft/bring-your-own-agent.md` where they list runners. Verify: the README test passes, and every page
  that lists runners names `lm-studio`.

## 12. File the gaps (design D13)

- [ ] 12.1 For each D13 candidate that building confirmed, check #56's, #162's, #292–#296's and #319's issues, and file
  it: troupe issues on the troupe roadmap board, citing this change, and library requests on lmstudio-python, linked
  from a troupe issue. Verify: each troupe issue shows the board in `gh issue view <n> --json projectItems`, and D13
  lists its number, or says why a candidate wasn't filed.

## 13. Verify the whole change

- [ ] 13.1 Run `uv run scripts/check.py` (the full check). Verify: it passes, and its summary line is quoted in the
  last commit's message or the pull request.
- [ ] 13.2 Mark the pull request ready once #333 and the infrastructure Purpose pull request have merged and the review
  of its last push is clean, and confirm CI passes on Linux, macOS and Windows. Verify: `gh pr checks` shows every job
  passing on the head commit.

## Workflow follow-up

- Archive on the branch (`/opsx:archive`) after the review is acted on, before the owner merges.
- After the merge, comment on troupe#291 with the pull request and the archived change, close it if the PR didn't,
  and check its card says Done. Comment on troupe#56 that LM Studio is done, and leave it for the owner to close.
