# Tasks

## 1. Baseline and failing tests

- [ ] 1.1 Record the baseline for the differential check (design D3). Write a scratch script, outside the repo, that
  runs `troupe.cli.parser.parse` over every line of 0 to 5 tokens after the command name. Each command draws from
  its own tokens: `status` from `x 5 -- --json --limit -5`; `logs` from `x -- --json --follow`; `perform` from
  `x -- --runner --no-effect-check --expect`; `echo` (declared as in `test_cli.py`) from `x -- --upper -5`;
  `choose` from `5 x -- --colour red`. Save each line's outcome to a file: the namespace, or the error code and
  details. Run it on this branch before any code change. Verify that exactly 77 lines give `usage.invalid`, every
  one with the problem ending `unrecognized arguments: --`, and that every one of those lines ends with `--`.
- [ ] 1.2 Add `test_a_trailing_separator_after_the_filled_positionals_parses_as_the_line_without_it` to
  `packages/troupe/tests/test_cli.py`, parametrised over the six lines in design D3 (the issue's
  `status x --json --` first). Each must parse, through `parse(argv, CHECKED)`, to a namespace equal to the one for
  the same line without its trailing `--`. Verify that it fails on all six before the fix, with `usage.invalid`.
- [ ] 1.3 Add the property test `test_a_trailing_separator_never_changes_the_outcome` next to the existing property
  test (design D3). It draws from `command_lines()`, uses `assume` to skip lines that contain `--`, and checks that
  `line` and `line + ["--"]` give the same outcome: equal `show_version`, `command`, `vars(arguments)` and
  `help_text`, or the same error `code` and `details`. Use the same settings as the existing property test. Verify
  that it fails before the fix (run it until hypothesis reports a counterexample of the 1.1 shape, or confirm it
  with `@example(["status", "x", "--json"])` added to the test, which stays).

## 2. Fix

- [ ] 2.1 In `packages/troupe/src/troupe/cli/parser.py`, give `_Scan` a `separator: int | None` field set to the
  index of the `--` the scan reads as the separator. In `parse`, hand argparse `argv[:-1]` when that separator is
  the last token, and `argv` otherwise (design D2). Leave `_scan`'s refusals, `_check` and the help/version path
  unchanged. Verify that the tests from 1.2 and 1.3 pass, and that `uv run pytest packages/troupe/tests/test_cli.py`
  passes, including `test_every_refusal_is_a_named_usage_shape_with_no_prefix` and the existing `--` tests
  (`status -- -5 -6`, `status --limit --`, `-- echo x`).
- [ ] 2.2 Add the rule to `parser.py`'s module docstring, next to the `--` rule: a `--` with nothing after it
  changes nothing, and why argparse needs the parser's help with it (it consumes `--` only alongside positionals).
  Verify by reading the docstring against the code and the cli delta spec.
- [ ] 2.3 Rerun the 1.1 sweep after the fix and diff it against the baseline. Verify that only the 77 baseline
  `usage.invalid` lines differ, that each now parses, and that each parses to the same namespace as its line
  without the trailing `--`. Record the counts in the commit message.

## 3. Check

- [ ] 3.1 Run `openspec validate status-refused --strict` and verify it passes.
- [ ] 3.2 Run `uv run scripts/check.py` and verify that all gates pass (ruff, mypy --strict, the full test suite).

## Workflow follow-up

- Open the PR with `Closes #82`. CI must pass on Linux, macOS and Windows, Python 3.12 and 3.13.
- Archive the change on the branch (`/opsx:archive`) before merging, so the cli spec gains the delta.
- After the merge, comment on #82 with the PR and the archived change, including D1's answer to the issue's
  "To decide".
