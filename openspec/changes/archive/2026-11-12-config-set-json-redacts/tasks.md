# Tasks

## 1. Unreadable JSON names where and why, not the text (design D2)

- [x] 1.1 Give `StrictJSONError` a content-free `rule` and `line` / `column` (none when unknown): `JSONDecodeError`'s
  `msg` and position, "a key appears more than once in one object" without the key, the NaN / Infinity words, and
  "it isn't UTF-8" with the byte offset. Keep `str(error)` unchanged. Verify with unit tests in
  `test_strict_json_and_ulid.py` that `rule` never holds a canary placed in a string, a key or a
  repeated key, and that `str(error)` for troupe's own files is what it was.

## 2. The CLI never repeats a value it can't type (design D1, D2)

- [x] 2.1 Rewrite every refusal in `cli/values.py` so its `problem`, `fix` and `details` name the path and what the
  path takes, never the text: `--json`, boolean, number, list or group, and no single type. `--json` and list or
  group errors give D2's rule, and `line` and `column` in `details`, which the protocol's error schema gains for
  `config.invalid` (both copies, regenerated with `scripts/package_schemas.py`). Verify with `test_cli_config.py`: update the
  assertions at the boolean (line 207) and no-single-type tests, and add one per refusal that a canary in the value
  appears in neither standard error nor the raised error's fields.
- [x] 2.2 `@file` refusals: a file that isn't JSON or YAML names the file, the line and the column (ruamel's
  `problem_mark`, D2's position for JSON), never ruamel's message or excerpt; a file that isn't UTF-8 says so with the
  byte offset. Verify with tests where the broken line of a `.yaml` and a `.json` file holds a canary.
- [x] 2.3 Add a hypothesis property test: for each kind `value_of` reads (boolean, integer, number, list, group, no
  single type, `--json`), generated text holding a canary that the kind refuses gives an error whose `problem`,
  `fix` and JSON-dumped `details` hold no part of the canary. Verify it fails on main's `values.py` first, then passes.

## 3. A malformed path shows only what was read (design D6)

- [x] 3.1 In `config_paths._malformed`, show `text[: offset + 1]` (the whole text only when reading failed at its
  end) in `problem` and `details.text`; the dot-before-bracket fix shows the corrected text up to the end of that
  bracket, and correct the error schema's description of `details.text` (both copies). Verify: `test_config_paths.py`'s property test asserts `details.text` is a prefix of the text ending at
  `offset`; add cases for `config set 'a]b=<canary>'`, `runtimes.box.endpoint.=<canary URL>`, and `config unset` /
  `config get` given `path=<canary URL>`, checking standard error and the error's fields; every spec scenario of "A
  malformed config path is refused" still passes, `a.[b]`'s fix still says `a[b]`.

## 4. Core's config check never repeats a value it refuses for its shape (design D3, D4, D5)

- [x] 4.1 `_rule`'s `enum` lists the values the schema takes, without "not X"; its fallback builds words from the
  validator and its value per D4, never `error.message`. Verify with `test_config_kinds.py` cases for each
  validator the config and options schemas use (each with a canary instance), and update `test_cli_config.py` line
  332's assertion.
- [x] 4.2 Add a test that walks the config schemas and every bundled runner's options schema and fails when one uses
  a validator `_rule` has no words for. Verify it fails when a validator is removed from `_rule`'s table.
- [x] 4.3 Give the SDK's `PatternError` a `rule` attribute (message unchanged), and build core's effect-pattern
  problem, fix and details from the list, the pattern's position and `rule`, never the pattern (D5, spec: effects).
  Verify: the SDK's pattern tests pass unchanged, and a new SDK test checks `rule` holds no part of the pattern;
  `test_config_kinds.py` line 290 asserts the position and rule and that `/tmp/**` is absent; a test per
  `PatternError` rule with a canary in the pattern finds it in none of `problem`, `fix` or `details`.
- [x] 4.4 Verify the D3 exceptions still name their value: the existing tests for an unknown runner, an undefined
  runtime and an uncovered `expect` path pass unchanged.

## 5. Canary tests through the CLI (spec: config, "A refused config value is repeated nowhere")

- [x] 5.1 Add `packages/troupe/tests/test_config_value_echo.py` with one test per scenario of the new requirement,
  driven through `troupe.cli.main` with the canary `https://user:<canary>@example.com/v1` (or the canary alone where
  the field takes no URL): `--json` set, each untyped kind, a value file, an enum, a malformed path before a value,
  `unset` / `get` given a value, and the effects scenario "A pattern holding a password". Each asserts the exit code, that the path is named, and that the canary and
  `example.com` appear in neither standard output, standard error, nor the client message (the core refusals called
  through the dispatcher, checking the error's `problem`, `fix` and `details`). Verify the module fails on main and
  passes on the branch.
- [x] 5.2 Add the scenario "A name is still named" as a test (`actors.tester.runtime=nowhere` names `nowhere` and the
  command that defines it). Verify it passes.

## 6. Docs and check

- [x] 6.1 Search `docs/` and the CLI's help text for any shown error that quotes a refused value (`isn't JSON`,
  `true or false, not`, `must be one of`, `isn't a config path`, a quoted effect pattern) and update each to the new wording; verify the docs
  check passes. (Rechecked at apply: no page or help text shows one; the SDK README now mentions `PatternError.rule`.
  The docs check runs in 6.2.)
- [x] 6.2 Run `uv run scripts/check.py` and record the test count; `openspec validate config-set-json-redacts --strict`
  passes. (On `8a2b7345`, the last commit outside `openspec/`, after the review fixes in 7.1 to 7.6: all gates
  passed, 5705 passed and 16 skipped. Strict validation passes.)
- [x] 6.3 Run issue #374's command by hand in a scratch theatre and record the before and after output in the PR.
  (Run, with the malformed-path, unset and effect-pattern cases too; none shows the password. The before is the
  issue's own output. Both go in the PR body.)
- [x] 6.4 Open a draft PR that closes #374, and see CI pass on Linux, macOS and Windows once it's marked ready.
  (PR #384. After review fixes up to `8a2b7345`, the last commit outside `openspec/`, CI run 43037972885 on
  `a9e71f49` passed all 12 legs, Linux, macOS and Windows on Python 3.12 to 3.15, on its second attempt: the first
  failed one macOS leg on an openai runner test this PR doesn't reach, filed as #392.)

## 7. A key from inside a value (design D7, review of #384)

- [x] 7.1 Pass config-set's operation paths to core's check, and never name a key no operation path reaches: an
  unknown field is refused at the value's path listing the fields the schema defines; a runtime or actor name that
  isn't one at `runtimes` or `actors`. Keep moved options' refusal, and naming for merges and perform. Verify with
  `test_config_kinds.py` (typed, value, nothing typed, names) and `test_config_value_echo.py` (a runtime's field, an
  option, a runtime's name, an actor's name, a typed misspelt field), each with a canary; update
  `test_cli_config.py`'s unknown price field test. (All pass; the price test now checks `currency` isn't named, and
  a new test names a field typed as a path.)
- [x] 7.2 Name an uncovered `expect` path by its position, never the path, with a fix that is the covering
  `troupe config set` with a placeholder for the new pattern (design D3, review of #384; owner chose the placeholder). Verify with a canary test in `test_config_kinds.py` and
  `test_config_value_echo.py`, and update the expect tests in `test_config_kinds.py`, `test_perform.py` and
  `test_config_merge.py`. (All pass.)
- [x] 7.3 Show a malformed path's text only up to the `[` of a bracket it failed inside, since an `=` there doesn't
  end the path (design D6, review of #384). Verify with canary cases in `test_config_paths.py` for an escape at the
  end and an unknown escape inside an open bracket, which fail on `899314ab`, and the property test's prefix check.
  (All pass.)
- [x] 7.4 Refuse a `config set` argument with no `=` by its position, never quoting it: a value typed after a space
  instead of an `=` is read as a path (review of #384, after archive). Verify with two canary tests in
  `test_config_value_echo.py`, which fail on `b8c822bb`, a scenario in the config spec, and the updated
  no-`=` tests. (All pass.)
- [x] 7.5 Refuse a rule broken under a map key from inside a value (`prices`, free-form options) at the map's path,
  never naming the key (design D7, review of #384, after archive). Verify with canary tests in `test_config_kinds.py`
  (a type, a missing and an extra field) and `test_config_value_echo.py`, which fail on `292bc734`, and a scenario in
  the config spec. (All pass; a map key typed as a path is still named.)
- [x] 7.6 Name a null inside a value by the value's place, never the keys leading to it, in the request decoder and in
  core (design D7). Verify with canary tests in `test_client_messages.py`, `test_config_changes.py` and
  `test_config_value_echo.py`, which fail on `292bc734`. (All pass; a list position is still named.)

## Workflow follow-up

- Act on Claude's review of the last push, archive the change on the branch, and ask the owner to merge.
- After the merge, comment on #374 with the PR and the archived change, check it's closed and its card on the roadmap
  board says Done.
