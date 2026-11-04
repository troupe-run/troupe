# Tasks

## 1. Scaffold the plugin and wire it into the workspace (design D1, D2)

- [x] 1.1 Create `plugins/runner-ollama/`:
  - `pyproject.toml`: `troupe-runner-ollama`, at the version a new package starts at today (check what the last new
    member used and what `scripts/bundle.py` and the release tests expect), `requires-python` as the other runners'
    have it, `dependencies = ["troupe-plugin-sdk"]`, and the script `troupe-runner-ollama`;
  - `LICENSE` (Apache-2.0, copied), `CHANGELOG.md`, and a stub `README.md`;
  - `src/troupe_runner_ollama/`, holding `__init__.py` (`NAME = "ollama"`, `__version__`), `py.typed` and
    `defaults.py` with D11's settings, each documented.

  Verify: `uv sync` succeeds, and `uv run python -c "import troupe_runner_ollama"` exits 0.
- [x] 1.2 Wire the member in:
  - the root `pyproject.toml`: `[tool.uv.sources]`, the dev group, ruff `src`, mypy `files` and `mypy_path`, pytest
    `testpaths`, import-linter `root_packages`, and the plugin's module in `plugins import nothing from troupe`, in
    `plugins are independent of each other`, and in the forbidden list of core's contracts;
  - `release-please-config.json` and `.release-please-manifest.json`;
  - `troupe-run`'s dependencies;
  - a `runner_ollama` scope in `scripts/check-paths.toml` covering `src/**`, `tests/**`, `fixtures/**`, `tools/**`,
    the README, the LICENSE and the CHANGELOG, with the plugin's tests listed wherever the other runners' are.

  Verify: these pass: `uv run lint-imports`, `uv run pytest scripts/tests/workspace`, and the bundle, plugin-import
  and check-paths tests. Then make a scratch module in the plugin that imports `troupe`, check that `lint-imports`
  fails, and remove it.
- [x] 1.3 Update the quality-check spec's scenarios in tests (spec: quality-check). Verify: a test in the check-paths
  suite shows that a commit staging only `plugins/runner-ollama/src/` gets `--scope runner_ollama`, and that the
  `plugin_sdk` scope's reached suites include `runner_ollama`'s.

## 2. Options, schemas and errors (design D10, D11)

- [x] 2.1 Add `schemas/options.schema.json` and `schemas/errors.schema.json` in the package, with `$id`s under
  `https://troupe.run/plugins/runner-ollama/`. The options schema has D11's options, `model` required, and the
  endpoint pattern from D10. The errors schema has D11's five codes and their closed `details`. Verify: a schema test,
  following `test_claude_code_schemas.py`, loads both with the contract's schemas and checks each is draft 2020-12 and
  passes the protocol's strictness check. A `run/start` with the documented options validates against the bound
  schema, and one with `troupeConformanceUnknownOption` doesn't.
- [x] 2.2 Add `options.py`: `parse_options(value) -> Options`, raising an error that carries a code, `where`, a
  problem and a fix, for `ollama.unknown-option` and `ollama.invalid-options`. Verify with `test_ollama_options.py`:
  - one accepted value and one refused value for each rule in D10 and D11, including `maxTurns` 0 and 1001,
    `think` `"maximum"`, a missing or empty `model`, and an endpoint with user info, a path, a query, a fragment, or
    an `ftp` scheme;
  - the refusal of `http://user:secret@127.0.0.1:11434` doesn't contain `secret` anywhere in its problem, fix or
    details;
  - a hypothesis test, fed near-valid and arbitrary JSON objects, asserting that `parse_options` and the published
    schema accept and refuse exactly the same ones.

## 3. The engine client and the fake Ollama (design D2, D9, D12)

- [ ] 3.1 Add `client.py`, the `/api/*` client on `http.client`, with these parts:
  - `version()` and `show(model)` with the preflight timeout;
  - `chat(body)`, which yields lines with the idle timeout and `LINE_MAX_BYTES`;
  - `close()`, which shuts down the socket in flight;
  - D9's classification of failures into retried (with reason) and final.

  Verify with `test_ollama_client.py` against the fake (3.2):
  - each status in D9 is classified as D9 says;
  - a silent stream is `network`. A dropped connection ends the lines before Ollama's `done` line, since
    http.client reads a stream cut short as ended, and 5.1 checks the conversation makes that a `network` retry;
  - a line over `LINE_MAX_BYTES` is a stream error and is never read whole;
  - `close()` from another thread wakes a blocked read within a second, on all three platforms.
- [x] 3.2 Add `tests/fake_ollama.py` (D12), and a test that runs it directly and checks each scripted answer, delay,
  mid-stream close and recorded request. Verify: that test passes.
## 4. Real Ollama fixtures and the capture tool (design D12)

- [x] 4.1 Add `tools/capture_ollama.py`. It drives a loopback Ollama through the runner's client (it imports 3.1), in a temporary workspace, with a fixed direction, model, `seed` and `temperature` 0. It writes
  `exchange.jsonl` and `provenance.json` for a named fixture, and refuses an endpoint that isn't loopback. Verify: a
  unit test runs the tool against the fake endpoint from 3.2 and checks the files it writes, and a second checks it
  refuses `http://example.com:11434`.
- [x] 4.2 Capture from the owner's Ollama, already installed and running (owner, 2026-11-04: Ollama 0.40.14 at
  `/opt/homebrew/bin/ollama`, with `qwen3.5:4b`, `qwen3.5:0.8b` and `qwen3:0.6b` pulled; nothing is pulled for this
  change). Capture with the smallest model that does each one, so captures stay quick: `success-with-tools`,
  `refused-by-effects`, `thinking`, `model-not-found`, and `context-overflow` (`contextLength` 512 and a `Read` of a
  file larger than that, which `truncate: false` turns into Ollama's 400). For `no-tools-capability`, make a model
  without the `tools` capability from `qwen3:0.6b` with `ollama create` and a template with no tools section. Remove
  it with `ollama rm` afterwards, and say so in the provenance. Record each provenance's Ollama version.
  Hand-write the failure fixtures D12 lists (503, dropped connection, an `error` line), and mark their
  provenance hand-written. As done (2026-11-04): the events of every fixture are recorded, by the capture or by
  replaying hand-written answers, then reviewed by hand, since real tool calls carry random ids only a recording
  reproduces. A silent stream isn't a fixture: the runner's idle limit is a named 300 s, so it stays covered by the
  client's and the conversation's tests, which lower it. Ollama 0.40.14 still listed `tools` for the made model (a
  qwen3-family model's capabilities come from its renderer), so `no-tools-capability`'s capabilities were edited to
  `["completion"]` by hand, as its provenance says. Verify: every fixture directory has its three files, the provenance test (5.2)
  passes, and `ollama list` afterwards shows only the models that were there before.
- [x] 4.3 Record what the captures settle (design D15, D16): the 400 Ollama sends for a request over the window, in
  `context-overflow`; that `prompt_eval_cached_count` is reported apart from `prompt_eval_count`; and where
  `/api/show` gives the model's maximum context. Write each into the plugin README's usage and context sections,
  citing its fixture, and open a follow-up issue (on the board) to map `prompt_eval_cached_count` to
  `cacheReadTokens`. Verify: the README states each one and cites its fixture, and the issue exists on the board.
- [x] 4.4 Add `requirements.json` (design D16) beside the schemas, holding `ollama` at least `0.12.6` and why, and
  `requirements.py`, which loads it and compares a reported version. It refuses an unknown field, a malformed
  `minimum`, and a version it can't read. Verify with `test_ollama_requirements.py`:
  - the published file's one requirement and its reason (spec: "The published requirement");
  - comparing `0.12.5`, `0.12.6`, `0.12.10`, `0.40.14`, `0.12.6-rc1` and `1.0` with `0.12.6`;
  - an unreadable version, an unknown field and a malformed `minimum` are each refused, naming what's wrong;
  - with the data changed to `0.50.0` in a temporary copy, `0.40.14` doesn't meet it (spec: "The check reads the
    data").

## 5. The conversation and the mapping (design D5, D6, D7, D8)

- [x] 5.1 Add `conversation.py`: it builds the first request (D5), gathers an answer from its lines, appends the
  `assistant` and `tool` messages, makes call ids, and yields transcript records and events as D6, D7 and D8 say,
  numbered with the SDK's `EventNumbering` and carried out with `Tools.for_declaration`. Verify with
  `test_ollama_conversation.py`, against scripted answers with no network:
  - one test per spec scenario for the character and direction, the tools offered, `contextLength` and the other
    options, tool calls (allowed, refused, two in one answer, no id, no name, string arguments), the loop's end, the
    turn limit, turns and thinking, the result's counts (and a counter no answer reported left out), Ollama's errors,
    `done_reason` `length`, and summaries cut below `eventMaxBytes`;
  - the context window (D15): `num_ctx` is always sent (the option, the default, and the default lowered to a smaller
    model maximum), every request has `truncate` and `shift` both `false`, and a status-400 refusal gets no further
    request and ends in an `error` result holding Ollama's message and naming the window and `contextLength`;
  - a stream that ends before Ollama's `done` line is a `network` retry (3.1 leaves this to the conversation);
  - one tool result fits the window (D15): the `ToolLimits` given to the SDK for the default window, for
    `contextLength` 8192 and 32768, and for a window so large that every limit stays at the SDK's default; a 200 KB
    file read through the conversation gives a `tool` message within the budget that says where it stopped; and a
    `Grep` over very long lines is cut with the note;
  - the transcript scenarios: the first body once, each added message verbatim as it appears inside the next
    request's body (checked by finding its bytes there), no re-sent history, and a non-UTF-8 line as `base64`;
  - a record that leads to an event comes before it.
- [x] 5.2 Add `test_ollama_fixtures.py`. For every fixture, replaying it through the fake gives exactly its
  `exchange.jsonl` records and `events.json` events. Also check each provenance names Ollama's version, the model, the
  date and whether it was captured or hand-written, and that a secret scan (copied from the Claude Code runner's) finds
  nothing. Verify: the file passes with 4.2's fixtures.
- [x] 5.3 Add a hypothesis property test. It feeds the conversation random answer lines: random bytes, random JSON
  objects, mutated fixture lines, and tool calls with random names and arguments. It asserts the conversation never
  raises, and that every event validates against `run-event.schema.json`, fits `eventMaxBytes`, has its `tool_result`
  after its `tool_call`, and never follows a `result`. Verify: it passes at the `ci` profile. A scratch break (a
  `tool_result` sent before its call, reverted) makes it fail.

## 6. The runner process (design D3, D4)

- [ ] 6.1 Add `runner.py` and `__main__.py`: the JSON-RPC loop on the main thread, the preflight (D4) before
  answering `run/start`, the worker thread, the stdout lock, stopping, and D3's exit codes. Add `tests/ollama_harness.py`,
  following `claude_harness.py`, which validates every message against the bound schemas. Verify with
  `test_ollama_runner.py`:
  - every spec scenario for the handshake, the identification and `init`, the options' refusals, the endpoint (its
    default, another host, credentials), the preflight's refusals (each naming its fix), a missing
    `capabilities` field, a `contextLength` above the model's maximum, and `runner.requirement-unmet` for an
    Ollama reporting `0.12.5` and for one reporting a version that can't be read;
  - cancel while an answer streams slowly: the fake sees its connection closed, no event follows the acknowledgement,
    and the runner exits 0 within `STOP_GRACE_SECONDS` plus a margin;
  - end of input while a request waits, and `shutdown` after the result;
  - a second `run/start`;
  - an exception in the loop gives exit 1, a `log` error and an `error` result;
  - a run's environment holds nothing the test didn't give it, and `OLLAMA_HOST` set to another port is ignored.

  Run it on all three platforms in CI (task 10.1).
- [x] 6.2 Write the plugin README: what the runner does, the options and their defaults (D11, with the README test
  from the Claude Code runner checking every option has a row and every row an option), the endpoint and that any
  host is accepted, the preflight's errors and their fixes, the transcript's records and how to rebuild a request,
  retries, cancelling, exit codes, usage, the context window (its default, why, raising `contextLength`, and how a run that outgrows it ends, citing
  #279), the fixtures and how to
  capture them, and the live test. Add the plugin to `plugins/README.md`'s table. Verify: the README test passes, and
  every path the README links to exists.

## 7. The contract amendments (spec: runner-protocol; design D7, D9)

- [x] 7.1 Add `runner.requirement-unmet` (design D16) to the contract: `protocol/schemas/runner/errors.schema.json`
  and its packaged copy in core, with closed `details` (`requirement`, `wanted`, optional `found`), and its row in
  contributing/runners.md's error table. Verify: the SDK's and core's runner-schema tests cover the new code, both
  of the runner-protocol spec's new scenarios validate against the contract alone, the strictness check passes,
  and the packaged copy matches the protocol's.
- [ ] 7.2 Update `protocol/schemas/runner/run-transcript.schema.json`'s description for D7. In contributing/runners.md,
  update "The transcript" for a runner that holds the conversation, "Run events"' `retry` row for a runner's own
  retries, and the runner list. Add a "Mapping an engine: Ollama" section with D6's table and D7's records. Verify:
  `uv run pytest packages/troupe/tests -k "runners_doc or schema"` passes, and the schemas' strictness check still
  passes.
- [ ] 7.3 Add tests for the two amended requirements' new scenarios: through the host, the Ollama runner's `tool`
  message is a stored transcript record before the next answer's lines, a three-request run stores the user message
  once, and a dropped connection gives a `retry` with reason `network` before the next attempt. Verify: the tests pass,
  in `test_ollama_host.py` (8.2).

## 8. troupe runs the Ollama runner (specs: runs, cli, config; design D12, D13)

- [ ] 8.1 Before changing the table, write a test that passes on main and must keep passing: a `scripted` actor's
  runner gets only the platform minimum. Then add the `ollama` entry to `interim.RUNNERS`, with no environment.
  Verify with `test_interim.py` and `test_perform.py`:
  - the scripted test still passes;
  - `ollama` resolves to the plugin's module;
  - `codex` is refused naming `claude-code`, `ollama` and `scripted`;
  - the spec's "The Ollama runner gets nothing new" scenario, using the stand-in's record of what reached it.
- [ ] 8.2 Add `packages/troupe/tests/ollama_stand_in.py` (D12) and `test_ollama_host.py`. For each fixture, run it
  through `run_actor` and check the outcome its `events.json` implies, and that every message validates. Also check:
  the stored transcript is the fixture's records byte for byte; a cancel mid-stream ends `cancelled` within
  `RUNNER_CANCEL_GRACE_SECONDS`; and each preflight refusal ends `could-not-start` with the runner's own error code.
  Verify: the file passes.
- [ ] 8.3 Add the Ollama runner, with the stand-in, to `test_runner_conformance.py`. Verify: every check passes.
- [ ] 8.4 Check `troupe config set actors.x.runner=ollama` with valid options, and with an option the runner doesn't
  define, beside the other runners' cases. Verify: the valid one is accepted, and the other is refused naming the
  runner's options schema.
- [ ] 8.5 Add the audition (D13): `OLLAMA_AUDITION_MODEL`, the `ollama` entry in `AUDITIONS`, and the perform
  step's note in `cli/init.py`, with the model read from the entries. Verify with the audition and init tests:
  - the config spec's two scenarios;
  - the cli spec's "The Ollama runner" and the updated `gemini` scenario;
  - "The audition's config is valid" covers `ollama`;
  - `troupe init --audition --runner ollama` in a scratch repository, then each printed step, with the stand-in as
    the endpoint (since the audition leaves `endpoint` unset, the test points it at the stand-in through config after
    init), ends `succeeded`.
- [ ] 8.6 Add `test_perform_ollama.py`: `troupe perform` on a theatre with an `ollama` actor and the
  `success-with-tools` stand-in. Verify: the run ends `succeeded`, its recorded start names runner `ollama` and engine
  `ollama` with the fixture's version and model, and the file the fixture wrote is in the worktree.
- [ ] 8.7 Update the user docs: "Runners today" in `docs/stagecraft/bring-your-own-agent.md` names the Ollama runner
  (no credential, the endpoint, any host accepted, `contextLength`), and `docs/opening-night/first-performance.md`'s
  "Choose a runner" shows an `ollama` actor and `troupe init --audition --runner ollama`. Verify:
  `uv run pytest packages/troupe/tests -k docs` passes, and the documented commands behave as written against a
  scratch theatre with the stand-in.

## 9. The opt-in live test (spec: ollama-runner, "A live test runs a real model only when asked"; design D14)

- [ ] 9.1 Add `packages/troupe/tests/test_ollama_live.py` as D14 says, skipped unless `TROUPE_LIVE_OLLAMA=1`, with a
  reason naming the variable and `TROUPE_LIVE_OLLAMA_MODEL`. Verify: without the variable,
  `uv run pytest packages/troupe/tests/test_ollama_live.py -rs` reports it skipped with that reason. CI's logs show it
  skipped on all three operating systems (10.1).
- [ ] 9.2 **Owner:** run the live test once on macOS with Ollama running and `qwen3.5:4b` pulled, and paste the outcome
  and what it printed into the PR. An agent session runs it only with the owner's go-ahead (as 4.2). Verify: the run
  reached a `result`, and its outcome isn't `crashed`.

## 10. Integration

- [ ] 10.1 Run `uv run scripts/check.py`. Verify: it passes (ruff, mypy --strict, import-linter and the full test
  suite). Then push, open the draft PR (`Closes #277`, citing #56), act on Claude's review, and mark it ready. Verify:
  every CI job passes on Linux, macOS and Windows. The Windows logs show the cancel and `close()` tests ran rather than
  being skipped, and show the live test skipped.
- [ ] 10.2 Open the troupe-run/infrastructure pull request that adds the `ollama-runner` spec's Purpose to
  `oob/troupe-spec-purposes.json`, following its `oob/README.md`, to merge after this one. Verify: its drift job's
  plan names `ollama-runner`, and the PR is linked from this one.

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging, so the PR lands code, tests and specs together. Validate with
  `openspec validate --strict` first.
- After the merge, check #277 is closed and its card says Done. Comment on #277 with the PR and the archived change.
  Comment on #56 that the Ollama half has landed. #56 stays open, blocked by #162, for LM Studio.
