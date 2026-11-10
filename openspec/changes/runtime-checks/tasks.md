# Tasks

Each group lands its own tests and docs. Each new test is run against the code before its group's change and seen to
fail (the count goes in the task), and `uv run scripts/check.py` passes before each commit.

## 1. Actor files hold every schema field (#288, design D10)

- [x] 1.1 Add a test in `packages/troupe/tests/test_config_files.py` that `FIELD_ORDER` equals the actor schema's
  `properties` in order, beside the `RUNTIME_FIELD_ORDER` one; see it fail on main. (Failed on main: the schema has
  4 more fields, `effects` first.)
- [x] 1.2 Add a test that sets every actor schema field through the config commands (the #288 command, extended to
  `options`) and checks `.troupe/actors/tester.yaml` holds each, in schema order, and validates against the actor
  schema; see it fail. (In `test_cli_config.py`; failed on main.)
- [x] 1.3 Extend `FIELD_ORDER` in `core/config/projection.py` to the schema's fields, character excepted; verify 1.1
  and 1.2 pass, and that an actor file troupe wrote before is replaced on the next flush (a test that writes the old
  form, records its hash as troupe's, and flushes). (`test_config_files.py` and `test_cli_config.py`: 108 passed.)
- [x] 1.4 Update the actor file's description in `contributing/config.md` and `docs/prompt-book/config-schema.md`
  where they list what the file holds; verify the docs check passes. (`config-schema.md` is generated from the schema
  and needed no change; `docs/the-company/roles-and-actors.md` now says what the file holds. `-m docs`: 179 passed.)

## 2. A sendable credential is visible ASCII (#329, design D7)

- [x] 2.1 Add SDK tests for `well_formed` (the plugin-sdk scenarios, plus a hypothesis test over all of Unicode that
  `well_formed(v)` is exactly "every character in `!`..`~`"); see the non-ASCII cases fail. (4 failed on main; a
  zero-width space was already refused.)
- [x] 2.2 Narrow `troupe_plugin_sdk.credential.well_formed` to visible ASCII, and its docstring; verify 2.1 passes.
- [x] 2.3 Add core and OpenAI runner tests for `sk-test-€abcdefgh` (`runtime.credential-malformed` before anything is
  recorded, holding no part of the value; `openai.malformed-credential` with no request sent); reword both errors'
  problem and fix to "a character a request header can't carry, such as a space, a line ending or a letter outside
  ASCII"; verify the tests pass. (5 new cases failed with the SDK change set aside; with it, 475 passed across the
  SDK, runtimes, perform-runtime and OpenAI runner suites.)
- [x] 2.4 Update `docs/stagecraft/runtimes.md` ("Just the key") and the OpenAI runner's README where they say
  "whitespace or a control character"; verify `grep -rn "whitespace or a control" docs contributing plugins` finds
  nothing stale. (Also `contributing/config.md`'s code table and the runner's `errors.schema.json` description.)

## 3. The SDK and runners never repeat a refused endpoint (#323, design D8)

- [x] 3.1 Add an SDK test that parsing a `run/start` whose `runtime.endpoint` is `https://user:<canary>@example.com/v1`
  raises a protocol error naming `runtime.endpoint` and holding neither the canary nor `example.com`, and one that a
  bad `runId` is still quoted; see the first fail. (Failed on main: the message quoted the whole endpoint.)
- [x] 3.2 Add `quoted` to `json_field`'s metadata and set it off for `RunStartRuntime.endpoint`, refusing with what an
  endpoint must be; verify 3.1 passes and the SDK's schema-agreement tests still pass. (As `unquoted`, design D8;
  SDK suite: 364 passed.)
- [x] 3.3 Add a runner-level test, for each runner on the SDK, that such a `run/start` is refused with
  `runner.invalid-params` and neither the JSON-RPC error nor the runner's standard error holds the canary.
  (`packages/troupe/tests/test_endpoint_user_info.py`: with the SDK fix set aside, claude-code, ollama and openai
  failed; scripted reads its script first and never repeats it either way.)
- [x] 3.4 Stop the OpenAI runner's `parse_endpoint` quoting an endpoint with user info, with a unit test calling it
  directly. (4 cases failed before; OpenAI runner suite: 335 passed.)
- [x] 3.5 Add CLI tests with a canary password: `troupe config set runtimes.box.endpoint=...` and
  `TROUPE_RUNTIME_OLLAMA_ENDPOINT` set to it, each checking the exit code, standard error and the client message hold
  no part of it; verify they pass (the environment path is already fixed by #298, so these guard it). (Both pass.
  Found on the way: `config set --json` quotes a value that isn't JSON in full, password included
  (`cli/values.py`); raised with the owner rather than folded in.)

## 4. Runtime fit in config (#334, design D1–D3, D9)

- [x] 4.1 Add the config tests from the runtimes spec's "An actor's runtime fits its runner" and the modified "An
  actor names its runtime" scenarios (each built-in pair, a config-defined runtime, a runtime change making its actor
  unfit, a merge doing the same, "no runtime fits"); see them fail. (`test_config_kinds.py` and `test_config_merge.py`: 8
  failed on main.)
- [x] 4.2 Add `RuntimeFit` and `Runner.fit` to `core/interim.py` (`ollama`: no credential, no path; `openai`: path
  required), following #338's field style, and `runtimes.unfit()` in `core/runtimes.py`, with unit tests of `unfit`
  over each reason, a trailing `/`, a port and an IPv6 host. (`test_runtimes.py`: 8 passed.)
- [x] 4.3 Pass `actor_problems` each runtime's built-in and theatre fields, judge fit in `_runtime_problems` with the
  runtime's path in `related`, skip a runtime with problems of its own, and list only fitting runtimes in the "needs
  a runtime" and "no such runtime" problems; verify 4.1 passes and mypy --strict is clean. (237 passed across the
  config and runtimes suites. `runtime_names` lost its last caller and was removed.)
- [x] 4.4 Add the differential test (D9): over the built-ins and generated runtimes, config's verdict equals
  `troupe_runner_ollama`'s and `troupe_runner_openai`'s own `checked`; place it where `scripts/check-paths.toml`
  reaches core and both plugins, and confirm with `scripts/check_paths_reach.py`. It fails for `openai` until 5.2.
  (`packages/troupe/tests/test_runtime_fit.py`; core tests already reach both plugins. It failed for `openai` on
  `http://127.0.0.1` until 5.2, then passed.)
- [x] 4.5 Document a runner's runtime fit in `contributing/runners.md` (a short section of its own: the guide has no
  list of the table's fields, and #338's `in_extra` appears only in its extras steps), and in
  `docs/stagecraft/runtimes.md` which built-in runtimes fit which runner; verify the docs check passes. (184
  passed.)

## 5. The OpenAI runner needs an endpoint with a path (#334, design D5)

- [x] 5.1 Add OpenAI runner tests from the openai-runner spec's "The runtime's endpoint has a path" (root, lone `/`,
  `/v1` reaching `/v1/responses`); see the first two fail. (3 cases failed, plus a published-code check given
  a pathless endpoint.)
- [x] 5.2 Refuse a pathless endpoint in `Runtime.checked` with `openai.no-runtime`, `where: runtime.endpoint`; verify
  5.1 and 4.4 pass, and update the runner's README and fixtures that use a pathless endpoint. (343 passed;
  no fixture used one; the README says so and its error table names it.)

## 6. Runtime fit at perform (#334, design D4)

- [x] 6.1 Add `runtime.unfit` to both copies of `error.schema.json` (details `actor`, `runner`, `runtime`, `reasons`,
  `from`, `fits`), with the perform tests from "Perform refuses a runtime that doesn't fit its runner" (endpoint
  variable with a path, credential variable set or unset, a rehearsal), each checking no runner started and nothing
  recorded, and that the error holds no endpoint and no name from `_CREDENTIAL_ENV`; see them fail. (5
  failed on main.)
- [x] 6.2 Pass the runner to `for_run` and judge fit after `resolve`, before the model and the credential; build
  `from` and `fits` (leaving out runtimes whose variables are malformed); verify 6.1 passes and the protocol guard
  (every catalogued code raised) passes in the full check. (`for_run` takes `runner` as a keyword;
  perform passes it. 579 passed across perform-runtime, runtimes, schemas and strictness; the full check at commit.)
- [x] 6.3 Add `runtime.unfit` to the errors `docs/stagecraft/runtimes.md` explains; verify the docs check passes.
  (The runtimes page names it in its fit table; the code table is `contributing/config.md`'s. 184 passed.)

## 7. `config get --resolved` names the setter (#306, design D6)

- [x] 7.1 Add tests: `config get --resolved runtimes.openai` with `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV=
  a3f9c2e17b4d8e05f6a1` shows `namedBy` from `env` and `set: false`, and neither the CLI output nor the client
  message holds any part of the name; a name from config or a built-in still shows as it is; a perform's run-started
  record still holds the name; see the first fail. (2 failed on main; the run-start test passed on main
  and now guards that the record keeps the name.)
- [x] 7.2 Make `runtime.schema.json#/$defs/resolved`'s `credential.env` a `oneOf` of `{value, source}` and `{namedBy,
  source: "env"}` (both copies, and every schema that copies it), update `Resolved.to_data`, the client message type
  and `cli/runtimes.py`; verify 7.1 passes and the schema tests pass. (The client type is `CredentialName`,
  with `value` or `namedBy`. 568 passed across config, perform-runtime, runtimes and schema suites.)
- [x] 7.3 Update `docs/stagecraft/runtimes.md` and `docs/prompt-book/cli.md` where they show `--resolved`'s credential
  line; verify the docs check passes. (`cli.md` shows no credential line, so only the runtimes page
  changed. 184 passed.)

## 8. Integration

- [ ] 8.1 Rebase onto main once #338 merges, keeping both `in_extra` and `fit` and both new error codes; run the full
  check and record the test count.
- [ ] 8.2 Run the #288 command and the #334 examples by hand in a scratch theatre (`troupe config set` for each pair
  in the issue, `troupe config get --resolved runtimes.openai` with a name in `_CREDENTIAL_ENV`) and record the
  output in the PR.
- [ ] 8.3 `openspec validate runtime-checks --strict` passes, and the runtimes delta's RENAMED-then-MODIFIED
  requirement applies as intended (checked with `openspec archive --dry-run` if available, else by reading the
  synced spec before archiving).
- [ ] 8.4 Open one draft PR whose body closes #323, #334, #329, #306 and #288, and see CI pass on Linux, macOS and
  Windows once it's marked ready.

## Workflow follow-up

- Tell the `track-b-26-333` session what this change adds to the runner table and the error catalogue (D11).
- Act on Claude's review of the last push, archive the change on the branch, and ask the owner to merge.
- After the merge, comment on each of the five issues with the PR and the archived change, check each is closed and
  its card on the roadmap board says Done.
