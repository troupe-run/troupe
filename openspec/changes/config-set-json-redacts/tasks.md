# Tasks

## 1. Unreadable JSON names where and why, not the text (design D2)

- [ ] 1.1 Give `StrictJSONError` a content-free `rule` and `line` / `column` (none when unknown): `JSONDecodeError`'s
  `msg` and position, "a key appears more than once in one object" without the key, the NaN / Infinity words, and
  "it isn't UTF-8" with the byte offset. Keep `str(error)` unchanged. Verify with unit tests in
  `test_strict_json_and_ulid.py` that `rule` never holds a canary placed in a string, a key or a
  repeated key, and that `str(error)` for troupe's own files is what it was.

## 2. The CLI never repeats a value it can't type (design D1, D2)

- [ ] 2.1 Rewrite every refusal in `cli/values.py` so its `problem`, `fix` and `details` name the path and what the
  path takes, never the text: `--json`, boolean, number, list or group, and no single type. `--json` and list or
  group errors give D2's rule, line and column, in `details` too. Verify with `test_cli_config.py`: update the
  assertions at the boolean (line 207) and no-single-type tests, and add one per refusal that a canary in the value
  appears in neither standard error nor the raised error's fields.
- [ ] 2.2 `@file` refusals: a file that isn't JSON or YAML names the file, the line and the column (ruamel's
  `problem_mark`, D2's position for JSON), never ruamel's message or excerpt; a file that isn't UTF-8 says so with the
  byte offset. Verify with tests where the broken line of a `.yaml` and a `.json` file holds a canary.
- [ ] 2.3 Add a hypothesis property test: for each kind `value_of` reads (boolean, integer, number, list, group, no
  single type, `--json`), generated text holding a canary that the kind refuses gives an error whose `problem`,
  `fix` and JSON-dumped `details` hold no part of the canary. Verify it fails on main's `values.py` first, then passes.

## 3. A malformed path shows only what was read (design D6)

- [ ] 3.1 In `config_paths._malformed`, show `text[: offset + 1]` (the whole text only when reading failed at its
  end) in `problem` and `details.text`; the dot-before-bracket fix shows the corrected text up to the end of that
  bracket. Verify: `test_config_paths.py`'s property test asserts `details.text` is a prefix of the text ending at
  `offset`; add cases for `config set 'a]b=<canary>'`, `runtimes.box.endpoint.=<canary URL>`, and `config unset` /
  `config get` given `path=<canary URL>`, checking standard error and the error's fields; every spec scenario of "A
  malformed config path is refused" still passes, `a.[b]`'s fix still says `a[b]`.

## 4. Core's config check never repeats a value it refuses for its shape (design D3, D4, D5)

- [ ] 4.1 `_rule`'s `enum` lists the values the schema takes, without "not X"; its fallback builds words from the
  validator and its value per D4, never `error.message`. Verify with `test_config_kinds.py` cases for each
  validator the config and options schemas use (each with a canary instance), and update `test_cli_config.py` line
  332's assertion.
- [ ] 4.2 Add a test that walks the config schemas and every bundled runner's options schema and fails when one uses
  a validator `_rule` has no words for. Verify it fails when a validator is removed from `_rule`'s table.
- [ ] 4.3 Give the SDK's `PatternError` a `rule` attribute (message unchanged), and build core's effect-pattern
  problem, fix and details from the list, the pattern's position and `rule`, never the pattern (D5, spec: effects).
  Verify: the SDK's pattern tests pass unchanged, and a new SDK test checks `rule` holds no part of the pattern;
  `test_config_kinds.py` line 290 asserts the position and rule and that `/tmp/**` is absent; a test per
  `PatternError` rule with a canary in the pattern finds it in none of `problem`, `fix` or `details`.
- [ ] 4.4 Verify the D3 exceptions still name their value: the existing tests for an unknown runner, an undefined
  runtime and an uncovered `expect` path pass unchanged.

## 5. Canary tests through the CLI (spec: config, "A refused config value is repeated nowhere")

- [ ] 5.1 Add `packages/troupe/tests/test_config_value_echo.py` with one test per scenario of the new requirement,
  driven through `troupe.cli.main` with the canary `https://user:<canary>@example.com/v1` (or the canary alone where
  the field takes no URL): `--json` set, each untyped kind, a value file, an enum, a malformed path before a value,
  `unset` / `get` given a value, and the effects scenario "A pattern holding a password". Each asserts the exit code, that the path is named, and that the canary and
  `example.com` appear in neither standard output, standard error, nor the client message (the core refusals called
  through the dispatcher, checking the error's `problem`, `fix` and `details`). Verify the module fails on main and
  passes on the branch.
- [ ] 5.2 Add the scenario "A name is still named" as a test (`actors.tester.runtime=nowhere` names `nowhere` and the
  command that defines it). Verify it passes.

## 6. Docs and check

- [ ] 6.1 Search `docs/` and the CLI's help text for any shown error that quotes a refused value (`isn't JSON`,
  `true or false, not`, `must be one of`, `isn't a config path`, a quoted effect pattern) and update each to the new wording; verify the docs
  check passes. (None found at propose time; recheck.)
- [ ] 6.2 Run `uv run scripts/check.py` and record the test count; `openspec validate config-set-json-redacts --strict`
  passes.
- [ ] 6.3 Run issue #374's command by hand in a scratch theatre and record the before and after output in the PR.
- [ ] 6.4 Open a draft PR that closes #374, and see CI pass on Linux, macOS and Windows once it's marked ready.

## Workflow follow-up

- Act on Claude's review of the last push, archive the change on the branch, and ask the owner to merge.
- After the merge, comment on #374 with the PR and the archived change, check it's closed and its card on the roadmap
  board says Done.
