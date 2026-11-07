# Tasks

## 1. Never echo a refused runtime variable (spec: "A malformed runtime variable is an error"; design D1, D2)

- [x] 1.1 Before changing `_from_env`, add a test in `packages/troupe/tests/test_runtimes.py` that every
  `runtime.invalid-value` from the existing malformed cases (a non-URL endpoint, an endpoint with user info, a model
  with a newline, a variable name with a space, a `TROUPE_` name) holds the variable's name and what's accepted in
  `problem`, `fix` and `details`. Verify: it passes on the current code, so it guards what must stay the same.
- [x] 1.2 Add tests that the error holds no part of the value. A `hypothesis` property test generates malformed
  values for each of the three fields (including keys with `-` and spaces, and endpoints with a password in their user
  info) and checks the serialised error (problem, fix and details) contains none of them. Also add the spec's two named
  scenarios: a key in `_CREDENTIAL_ENV`, and `https://user:hunter2-secret@example.com/v1`. Verify: they fail on the
  current code with the value found in the error.
- [x] 1.3 Change `_from_env` so its problem names the variable and what it accepts without the value, and its details
  are `{variable, accepted}`. Verify: 1.1 and 1.2 pass, and the existing
  `test_a_malformed_variable_is_an_error_naming_it` is updated to the new details.
- [x] 1.4 Remove `value` from `runtime.invalid-value`'s details (`required` and `properties`) in
  `protocol/schemas/error.schema.json` and the troupe package's copy, in the same commit as 1.3 (the details schema
  is closed, so either half alone fails validation). Verify: `cmp` shows the two copies identical, and
  the protocol schema tests (`protocol_schemas`, `protocol_guard`) pass with the new details.
- [x] 1.5 Add a case to `test_perform_runtime.py`, and one through the client for `config get --resolved`, where
  `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV` holds a key: the command fails with `runtime.invalid-value`, nothing is
  recorded, and no message the client received holds the key. Verify: the tests pass.
- [x] 1.6 Update `contributing/config.md`'s row for `runtime.invalid-value` to say it names the variable and what's
  accepted, never the value. Verify: the row reads so, and `uv run scripts/check.py` passes.

## 2. One definition of a well-formed credential (design D5)

- [x] 2.1 Add `well_formed(value: str) -> bool` to `troupe_plugin_sdk.credential`, with tests in
  `packages/troupe-plugin-sdk/tests/test_credential.py`: false for a space, tab, `\r`, `\n`, NUL, DEL, a C1 control and
  a non-breaking space; true for a typical key (`sk-test-q7ZxW9pL4vR2`). Also add a `hypothesis` test that it agrees
  with "no character is whitespace or unprintable" on generated text. Verify: the tests pass.
- [x] 2.2 Make the OpenAI runner's `Runtime` use `well_formed` in place of its inline check, keeping
  `openai.malformed-credential` and its message. Verify: the runner's existing malformed-credential tests
  (`test_openai_runtime.py`, `test_openai_runner.py`) pass unchanged, and `uv run lint-imports` passes.

## 3. core refuses a malformed credential (spec: "A credential holding whitespace or a control character is refused"; design D3, D4)

- [x] 3.1 Catalogue `runtime.credential-malformed` in `core/errors.py` (exit code `FAILURE`) and in both copies of
  `error.schema.json` (closed details: `runtime` and `variable`, both required; 4.3 adds `namedBy` as the alternative to `variable`). This lands with the code that raises
  it (3.2), in the same commit, so `protocol_guard` never sees an unraised code. Verify: `protocol_guard` passes after
  3.2.
- [x] 3.2 In `for_run`, after the unset check and before the too-short one, refuse a value that isn't `well_formed`
  with `runtime.credential-malformed`, naming the runtime and the variable, never the value. Verify: tests in
  `test_runtimes.py` for a trailing `\r\n`, a space inside, and a short value with a line ending (`"abc\n"`, which gets
  `credential-malformed` and not `credential-too-short`); a well-formed key still starts; and the parametrised
  `test_no_refusal_holds_any_part_of_the_value` gains the malformed case. Each error passes the error schema.
- [x] 3.3 Add the malformed key to `test_perform_runtime.py`'s `test_a_refused_runtime_records_nothing`, and check
  that no runner was launched (the scripted runner's script would leave a mark it can be seen to have run). Also check
  that a rehearsal is refused the same way. Verify: the tests pass, and fail when the check in 3.2 is removed.
- [x] 3.4 Add `runtime.credential-malformed` to `contributing/config.md`'s error table ("names the runtime and the
  variable, never the value"). In the OpenAI runner's README, say that troupe refuses such a key before the runner is
  started, and that the runner still checks. Verify: `uv run pytest packages/troupe-plugin-sdk/tests/test_readme.py`
  and any README tests for the runner pass, and `uv run scripts/check.py` passes.

## 4. A credential refusal never repeats a name from the environment (spec: "A refusal never repeats a credential variable's name taken from the environment"; design D6)

- [x] 4.1 Add tests in `test_runtimes.py`, one per code (`credential-unset`, `credential-malformed`,
  `credential-too-short`), where `TROUPE_RUNTIME_MYHOST_CREDENTIAL_ENV` holds a hex name such as
  `a3f9c2e17b4d8e05f6a1` (set to a malformed or short value for the last two). Each asserts the details are
  `{runtime, namedBy: "TROUPE_RUNTIME_MYHOST_CREDENTIAL_ENV"}` and that the serialised error holds no part of the name.
  Also add one per code with the name from config (`runtimes.myhost.credential.env=K`) asserting `{runtime, variable:
  "K"}`, and one from the built-in `openai` naming `OPENAI_API_KEY`. Verify: the environment cases fail on the code
  after group 3, the config and built-in ones pass.
- [x] 4.2 Add one helper in `troupe.core.runtimes` that, given the credential's `Sourced` name and the runtime, gives
  the words for the problem and fix and the `variable`/`namedBy` detail. Use it in all three refusals. Verify: 4.1
  passes, and `test_no_refusal_holds_any_part_of_the_value` gains environment-sourced cases.
- [x] 4.3 In both copies of `error.schema.json`, make the three codes' details take `runtime` and exactly one of
  `variable` and `namedBy` (`oneOf`, still `additionalProperties: false`), in the same commit as 4.2. Verify: `cmp`
  shows the copies identical; a schema test refuses details with both keys and with neither; `protocol_schemas` and
  `protocol_guard` pass.
- [x] 4.4 Add the spec's scenario to `test_perform_runtime.py`: `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV` is a hex name
  that isn't set, perform fails with `runtime.credential-unset` naming the `TROUPE_RUNTIME_` variable, nothing is
  recorded, and no client message holds the name. Verify: the test passes, and fails when 4.2's helper is bypassed.
- [x] 4.5 Update `contributing/config.md`'s rows for the three codes: each names the runtime and the variable, or the
  `TROUPE_RUNTIME_` variable when that set the name, never the value. Verify: `uv run scripts/check.py` passes.

## 5. Whole-change checks

- [x] 5.1 Run `uv run pytest packages/troupe/tests/test_credential_leak.py` with a malformed credential variable added
  to its canary cases if it can take one, and the full `uv run scripts/check.py`. Verify: both pass, and the output is
  recorded in the commit or the PR.
- [ ] 5.2 `openspec validate runtime-variable-refusals --strict` passes, and CI passes on Linux, macOS and Windows on
  the PR's last code commit. Verify: cite the run.

## Workflow follow-up

- The follow-up for `config get --resolved` showing an environment-sourced name is #306, linked from the
  PR.
- Open a draft PR that closes #298, act on Claude's review of the last push, then mark it ready.
- Archive the change on the branch before merging. No spec Purpose changes, so infrastructure's
  `oob/troupe-spec-purposes.json` needs no update.
- After the owner merges, comment on #298 with the PR and the archived change, check that it's closed and that its
  card on the troupe roadmap is Done.
