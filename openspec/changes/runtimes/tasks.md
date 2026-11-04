# Tasks

## 1. The protocol: the runtime, the actor, run start, the run's start, config get

- [x] 1.1 Add `protocol/schemas/config/runtime.schema.json` (D1: closed; `endpoint`, `model`, `credential.env`, all
  optional; the URL and variable-name patterns, `TROUPE_` refused case-insensitively). Verify the protocol strictness
  check passes, and schema tests: user info, a query, a fragment, `ftp://`, `MY KEY` and `troupe_x` are refused;
  `https://api.openai.com/v1` and `OPENAI_API_KEY` validate.
- [x] 1.2 Add `runtime` and `model` to `config/actor.schema.json`, and regenerate core's config types (actor and
  runtime). Verify `scripts/check.py`'s generated-types check passes and the type/schema agreement property test
  covers both kinds.
- [x] 1.3 Add the optional closed `runtime` (`name`, `endpoint`, `model`, `credential` boolean, all required) to
  `runner/run-start.schema.json`, and `runtime` (D8) to `events/run-started.schema.json`. Verify schema tests: a
  `run/start` with a runtime validates, one with a `value` or `env` inside it doesn't, and one without stays valid
  (runner-protocol delta, "Run start carries the run's runtime").
- [x] 1.4 Add `resolved` to `client/config-get-request.schema.json`, `runtimes` to its result, the runtime to the
  perform rehearsal's schema, and D10's six codes to the error catalogue with closed details. Verify the catalogue
  test refuses an unlisted code and each code's details are closed.
- [x] 1.5 Commit the protocol's changes as `feat(protocol)` (release-please writes the CHANGELOG from it) and update `contributing/runners.md` with the hand-off (run start's
  `runtime`, `TROUPE_RUNTIME_CREDENTIAL`, never sending it back). Verify `uv run scripts/docs_reference.py` regenerates
  `docs/prompt-book/config-schema.md` with the runtime kind, and the docs check passes.

## 2. The SDK

- [x] 2.1 Add `runtime` to the SDK's `RunStartParams`, and a helper that reads `TROUPE_RUNTIME_CREDENTIAL` only when
  `runtime.credential` is true (refusing a mismatch either way). Verify the SDK's schema-agreement tests pass and fail
  when the field is removed, and unit tests for the helper's three cases.

## 3. Core: built-ins, resolution and config rules

- [x] 3.1 Add `RUNTIMES` (D2) and `CREDENTIAL_MIN_BYTES` to `troupe.core.defaults`. Verify a test that each built-in
  validates against the runtime schema and none names a model.
- [x] 3.2 Add `troupe.core.runtimes`: resolve a runtime from defaults, theatre config and the session's environment
  into values with sources (D3), the model's order (env, actor, theatre), and `runtime.invalid-value`. Verify tests
  for each runtimes-spec scenario under "Theatre config overrides a built-in field by field", "The person's
  environment overrides a runtime's values", "A malformed runtime variable is an error" and "The run's model comes
  from the environment, the actor, then the runtime", and a hypothesis test that the variable checks and the schema
  accept the same endpoints and names.
- [x] 3.3 Add the run-time checks: `runtime.no-model`, `runtime.credential-unset`, `runtime.insecure-endpoint` (literal
  loopback only, D7) and `runtime.credential-too-short`, reading the credential through the platform seam's name
  matching. Verify tests for each scenario, including `localhost`, `127.0.0.2`, `[::1]`, and that no error's text or
  details holds any part of the value.
- [x] 3.4 Add the `runtimes` kind to `config/kinds.py` and `runtime: required | optional | none` to `interim.Runner`
  (`claude-code` none, `scripted` optional). Check the cross-kind rules (D4). Verify tests for the config delta's
  scenarios and the runtimes spec's "A runtime is a named service...", "A credential can't name troupe's own
  variables" and "An actor names its runtime and may set its model", including unsetting a used runtime and a merge
  that removes one becoming a conflict.

## 4. Core: projection and config get

- [x] 4.1 Project runtimes to `.troupe/runtimes/<name>.yaml` with both schema lines, and register the file kind.
  Verify tests for each config-files delta scenario, including a written file validating against its schema and a
  stray file refused.
- [x] 4.2 Add the resolved query to `config get` in core and `--resolved` to the CLI, rendering each value with its
  source and the credential's variable as set or unset. Verify tests for the runtimes spec's "Config get shows a
  runtime's resolved values and their sources", and that the CLI reference in `docs/prompt-book/cli.md` regenerates
  with `--resolved`.

## 5. Core: perform, the hand-off and masking

- [x] 5.1 Add the `Masker` (D6): strings in an event, record bytes, and a streaming mask for standard error, each for
  the raw and JSON-escaped forms. Verify unit tests, and hypothesis tests that no output holds the value however the
  input is chunked or what surrounds it.
- [x] 5.2 In perform, resolve the actor's runtime before anything is recorded, record it in `Run.Started` (D8), add it
  to `run/start`, and add `TROUPE_RUNTIME_CREDENTIAL` to the runner's environment after the table's variables. Verify
  tests for the runs delta's "A run's start records its runtime...", "A run uses the actor as config defines it"
  (the runtime reaches the runner) and "Perform passes a runner only the variables it is known to need" (the
  credential under troupe's name only, and a `TROUPE_RUNTIME_CREDENTIAL` in perform's own environment not passed).
- [x] 5.3 Apply the mask in the run host to run events, transcript records, standard error and the runner's errors,
  and to errors perform raises during the run. Verify tests for each scenario under "troupe masks the credential in
  everything it keeps from a run", including the split across two reads, and the runner-protocol delta's transcript
  scenarios.
- [x] 5.4 Show the runtime in a rehearsal, refusing what perform would. Verify a test for "A rehearsal shows the
  run's runtime".

## 6. The scripted runner

- [x] 6.1 Accept `run/start`'s runtime, and add the `checkRuntime` and `echoCredential` steps (D11) to the runner, its
  options schema and its README. Verify the scripted-runner delta's scenarios as tests, and the runner's schema tests.

## 7. The leak test and docs

- [x] 7.1 Write `test_credential_leak.py` (D12) and its check that it fails with masking turned off. Verify both pass,
  on Linux, macOS and Windows in CI. (Linux, macOS and Windows, Python 3.12 to 3.15: CI run 41819326602 on 6f9381f)
- [x] 7.2 Write `docs/stagecraft/runtimes.md`: defining and overriding a runtime, the environment variables, the
  credential by reference, `config get --resolved`, and the accepted risks of a theatre-chosen endpoint and variable
  (D7). Link it from the config and actor docs. Verify the docs check passes and each example command runs as written
  in a test theatre.

## 8. Follow-ups and records

- [x] 8.1 File the policy follow-up (policy limits the endpoints a credential may go to and the variables config may
  name as credentials, D7) on the board, and, if #277 has merged with its endpoint and model in its options, the
  follow-up moving the Ollama runner to a runtime. Verify each shows on the board with
  `gh issue view <n> --json projectItems`. (#286, on the board. #277's PR #283 hadn't merged, so its
  follow-up isn't filed: file it if #283 merges before this.)
- [x] 8.2 Open the troupe-run/infrastructure pull request recording the `runtimes` spec's Purpose in
  `oob/troupe-spec-purposes.json`, to merge after this one. Verify the record matches the spec's Purpose without
  its `Capability:` line, and the pull request names this one. (troupe-run/infrastructure#273,
  for #272, opened by the orchestrating session.)
- [x] 8.3 Check #162's design D2 against what landed, and comment on #162 with any difference. Verify the comment
  links this pull request. (It matched D2; the comment says what landed and links #287.)

## Workflow follow-up

- Act on Claude's review of the last push, mark the pull request ready, and wait for CI on Linux, macOS and Windows.
- Archive the change on the branch, then ask the owner to merge; merge the infrastructure pull request after.
- After the merge, comment on #278 with the pull request and the archived change, and check its card says Done.
