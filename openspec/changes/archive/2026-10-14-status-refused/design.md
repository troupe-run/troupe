# Design

## Context

See proposal.md, Why. `parse` in `packages/troupe/src/troupe/cli/parser.py` runs in three steps. `_scan` reads the
line: it refuses unknown commands, unknown flags and dash-leading values without a separator, and records what the
line gave. `_check` compares that with the command's declared arguments and raises the named usage errors. Then
argparse turns the accepted line into a namespace, and anything it still refuses is `usage.invalid`, the backstop.

`_scan` treats the first `--` after the command as the separator. Everything after it is a positional, and the `--`
itself is never a value. argparse handles `--` differently. It only consumes `--` while it is reading a stretch of
positionals. When all the positionals were filled before an option (`status x --json --`: `x` fills `run`, then
`--json`), nothing is left to take the trailing `--`, so argparse reports it as an unrecognized argument. Probed with
plain argparse on Python 3.12.0, 3.12.14, 3.13, 3.14 and 3.15, every case gave the same result:

| argv (after the command) | argparse |
|---|---|
| `x --json --` | unrecognized arguments: `--` |
| `x --limit 5 --` | unrecognized arguments: `--` |
| `x --` | `run='x'` |
| `--json --` | `run=None, json=True` |
| `--json x --` | `run='x', json=True` |
| `--json -- x` | `run='x', json=True` |
| `x --json -- y` | unrecognized arguments: `-- y` (troupe refuses first: `usage.extra-argument`, `y`) |
| `x -- --` | unrecognized arguments: `--` (troupe refuses first: `usage.extra-argument`, `--`) |

A sweep of `parse` over every line of up to five tokens, drawn from each command's own flags and values, found 77
lines that reach the backstop. All of them are the first row's shape: a trailing separator with nothing after it,
after the positionals were filled. No other shape reaches the backstop in that sweep.

## Goals / Non-Goals

**Goals:**
- troupe's checks and argparse agree on every line that ends with a separator.
- The issue's argv is pinned by a deterministic test, and the general rule by a property test.

**Non-Goals:**
- Changing how argparse treats `--` anywhere else, or replacing argparse.
- Changing the outcome of any line that doesn't reach the backstop today. Lines that parse today parse to the same
  namespace, and lines refused with a named code keep that code.
- Accepting a `--` before the command. `troupe -- echo x` stays refused (argparse-errors D8).

## Decisions

### D1. A separator with nothing after it is accepted and means nothing

This is the question the issue leaves open. Two answers:

- **Parse it (chosen).** `status x --json --` parses as `status x --json`. A `--` marks the tokens after it as
  values, and here there are none, so the line has exactly one reading. Nothing is guessed, so this doesn't conflict
  with "refuse rather than guess". It is also what `status x --`, `status --json --` and `logs abc --` already do,
  so whether a trailing `--` parses no longer depends on where the options happen to sit.
- **Refuse with a named code** (for example `usage.empty-separator`). Refusing only the shape argparse refuses would
  make the rule "a trailing `--` is refused when the positionals were filled before an option", which no user can
  predict. To be consistent it would have to refuse every trailing `--`, including `status x --`, which works
  today. That breaks working lines to forbid something that does no harm. Rejected.

Scripts that build a command line and always append `--` before a list of values that may be empty are the real
case this serves. With the fix, an empty list works wherever the options are.

### D2. The parser drops the trailing separator before argparse runs

`_Scan` records the index of the token it read as the separator (`separator: int | None`). In `parse`, if that
`--` is the last token of the line, argparse gets the line without it. Otherwise argparse gets the line unchanged.
The scan, the check and the help/version short-circuit all see the line as before. The scan already gives the
separator no positionals in this case, so the check needs no change.

Only the scan's separator is dropped. A later `--` is a value (`status x -- --`) and stays, and the check refuses
it as `usage.extra-argument` before argparse runs. A `--` that the scan reads while an option is still waiting for
its value (`status --limit --`) is that option's missing value, and the check raises `usage.missing-value` first,
as it does today.

*Alternative:* teach `_check` to refuse what argparse refuses. That is the "refuse" answer to D1, rejected above.

*Alternative:* pass argparse a line rebuilt from the scan, with options first and then `--` and the positionals.
That would also close this gap, but it changes what argparse sees for every line, not just this shape. That is
far more than the bug needs, and it risks the kind of regression #53 shipped and then fixed in 0f48fc5 (a new
layer in front of argparse quietly refusing a line main accepted). Rejected.

### D3. Tests: the argv pinned, the rule as a property

- **Deterministic:** a parametrised test over `status x --json --` (the issue's argv), `status x --limit 5 --`,
  `logs x --follow --`, `perform x --runner x --no-effect-check --`, `echo x --upper --` and
  `choose 5 --colour red --`. Each must parse to the same namespace as the same line without the `--`. These are
  real lines from the sweep, one per command, so the test doesn't depend on hypothesis finding them.
- **Property:** for a line drawn by the existing `command_lines` strategy with no `--` in it, `parse(line)` and
  `parse(line + ["--"])` give the same outcome: an equal `Parsed` (version flag, command, namespace, help text),
  or a `TroupeError` with the same code and details. This states the spec scenario "A trailing separator never
  changes the outcome" directly. Unlike the existing property test, it compares two outcomes, so it would also
  catch a fix that made the trailing `--` parse to a different namespace.
- **Non-goal check, as a differential:** before the change, run the scratch sweep (`parse` over every line of up
  to five tokens) on main and save each line's outcome. Run it again after the change. Only the 77 backstop lines
  may differ, and each must now parse. This is a one-off verification recorded in the task, not a committed test,
  since the property test covers the rule going forward.
- `test_every_refusal_is_a_named_usage_shape_with_no_prefix` is unchanged. It should stop finding this gap, and
  the deterministic test makes sure that doesn't depend on chance.

## Risks / Trade-offs

- [Dropping a token changes what argparse sees] → only a final `--` that the scan read as the separator, which by
  definition separates nothing. The differential sweep and the property test check that no other line changes.
- [A future argparse could start consuming a trailing `--` itself] → then dropping it is a no-op and the
  deterministic tests still pass. CI runs 3.12 and 3.13, and the probe above covers through 3.15.
- [The property test filters out lines containing `--`] → lines that already have a separator are covered by the
  existing property test and the `-- --` scenario. Appending a second `--` to them would make it a value, not a
  separator, which is a different claim.

## Migration Plan

None. No stored data, error codes, schemas or exit codes change.
