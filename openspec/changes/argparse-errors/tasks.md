# Tasks

## 1. No prefix in any usage problem

- [ ] 1.1 Add a test that `troupe perform tester --runner scripted` (through `main`, real commands) writes a first
  stderr line starting `troupe: ` and never `troupe: troupe:`, and that no usage error's problem data starts with
  `troupe:`, parametrised over every usage shape in the spec. Verify it fails on main for the argparse-reported shapes
- [ ] 1.2 Drop the prefix from `_Parser.error` and the `ArgumentError` wrapper in `parser.py`, building `usage.invalid`
  with the chosen command named and its help in the fix (design D5, D7); `_Parser.error` raises a marker that `parse`
  completes with the command. Verify 1.1 passes for the backstop path and the existing `test_cli.py` passes

## 2. The schema and catalogue for the new shapes

- [ ] 2.1 Add `usage.missing-argument`, `usage.missing-one-of`, `usage.conflicting-options`, `usage.extra-argument`,
  `usage.missing-value` and `usage.invalid-value` to `protocol/schemas/error.schema.json` with closed details, and
  give `usage.invalid` and `usage.unknown-flag` a `command` (string or null) (design D6). Add the six codes to
  `troupe.core.errors.CODES` with `ExitCode.USAGE`. Verify the catalogue-vs-schema test and the strictness test pass,
  and `usage.invalid` / `usage.unknown-flag` data without `command` no longer validates

## 3. Reading a command's declared arguments

- [ ] 3.1 Replace `_options_of` with `_declared(parser)`, a frozen troupe-owned description of a command's options
  (with whether each takes a value), positionals (with `nargs`) and exclusive groups (with `required`), the only reader
  of argparse internals (design D4). It refuses option `nargs` other than zero or one value, unsupported positional
  `nargs`, and side-effecting types such as `argparse.FileType`, as `internal.unexpected`. Verify a test pinning
  `_declared` against the real `perform`, `status` and `logs`, and tests that each refused declaration raises
- [ ] 3.2 Make the pre-scan record, for the chosen command, each given option's raw values and every positional value
  (including those after `--`), using `_declared`. Verify the existing pre-scan tests pass unchanged

## 4. The checks, one shape at a time (design D2, D5)

Each task adds the check, its error builder and its tests: through the real command named in the spec scenario, and
through a test command where the real ones can't reach a case. Each verifies the code, the details, the problem
wording, the fix naming `troupe <command> --help`, exit 2, empty stdout and schema validity.

- [ ] 4.1 `usage.missing-value`: an option taking a value is last, or followed by `--` or a flag-like token; the
  pre-scan stops swallowing that token. Verify `status --limit`, `status --limit --json` and
  `perform tester --runner`, and that `status --limit -5` still reaches argparse as today
- [ ] 4.2 `usage.conflicting-options`. Verify `perform ... --expect out.txt --no-effect-check`, and that
  `--expect a.txt --expect b.txt` is not a conflict
- [ ] 4.3 `usage.extra-argument`. Verify `status one two`, `logs abc def`, and `status -- -5 -6` naming `-6`
- [ ] 4.4 `usage.missing-argument`, required options then positionals in declaration order. Verify
  `perform tester --no-effect-check` names `--runner`, `perform tester` names `--runner` first, and `logs` names
  `<run>`
- [ ] 4.5 `usage.missing-one-of`. Verify `perform tester --runner scripted` gives the issue's expected text exactly:
  ``troupe: `troupe perform` needs one of --expect or --no-effect-check.`` and
  ``fix: Run `troupe perform --help` to see its options.``
- [ ] 4.6 `usage.invalid-value`, converting with the argument's `type` and checking `choices` (design D3). Verify
  `status --limit notanumber` names `status`, `--limit` and `notanumber`, and a test command with `choices` refuses an
  unlisted value
- [ ] 4.7 Check order (design D2). Verify a test with a line holding two problems (an extra value and a missing
  required option) reports the one D2 puts first
- [ ] 4.8 Update the `perform` scenarios' tests in `test_cli_runs.py` ("no effect check", "both effect check flags")
  to assert the new codes. Verify they pass

## 5. Unknown flags and the backstop name the command

- [ ] 5.1 The pre-scan's unknown-flag error, after a command is chosen, names the command in its problem and details
  and, with no near match, points at that command's help (design D5). Verify `status --bogus` and that `--bogus`
  before any command keeps pointing at `troupe --help` with `command: null`
- [ ] 5.2 Reach the backstop through a test command whose custom action fails only inside argparse. Verify it is
  `usage.invalid`, exits 2, names the command, has no prefix and validates against the schema

## 6. Property test and docs

- [ ] 6.1 Add a property test (hypothesis) generating command lines over the test commands' declared arguments:
  every refusal is a catalogued `usage.*` code, exit 2, with no `troupe:` prefix in its problem; every acceptance
  parses to a namespace. Verify it passes, and that reintroducing the prefix in one builder makes it fail
- [ ] 6.2 Add a command usage-error example to `docs/cli/README.md` (the `perform` one-of case) and say a command's
  errors point at its own help. Verify `test_cli_docs.py` passes and the example's text matches the CLI's output

## 7. Integration

- [ ] 7.1 Run each of the issue's reproduction lines and the six shapes from the proposal with `uv run troupe`, and
  record the output for the PR. Verify none prints `troupe: troupe:` and each fix names its command's help
- [ ] 7.2 Run `uv run scripts/check.py` (ruff, format, mypy --strict, import-linter, the full suite). Verify it passes
  locally and on CI on Linux, macOS and Windows

## Workflow follow-up

- Open the PR with `Closes #53`; archive the change on the branch before merging; after the merge, comment on #53
  with the PR and the archived change.
