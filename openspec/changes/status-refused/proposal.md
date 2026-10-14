# Proposal

Issue: #82.

## Why

`troupe status x --json --` is refused as `usage.invalid` ("`troupe status`: unrecognized arguments: --"). The cli
spec says every usage problem troupe's checks anticipate has a named code, and `usage.invalid` is only the backstop
for argparse refusing a line the checks accepted. #53's property test,
`test_every_refusal_is_a_named_usage_shape_with_no_prefix`, finds this gap whenever hypothesis happens to generate
the line. So until it's fixed, the test can fail any run for a reason that has nothing to do with that run's change.

The gap is wider than the one argv. A sweep of every line of up to five tokens over each command's own flags and
values (`status`, `logs`, `perform`, and the test commands `echo` and `choose`) found 77 that reach the backstop.
Every one has the same shape. All the command's positionals are filled before an option, and the line ends with
the separator `--` with nothing after it: `status x --json --`, `logs x --follow --`,
`perform x --runner x --no-effect-check --`, `echo x --upper --`, `choose 5 --colour red --`. argparse only consumes
`--` when it reads a stretch of positionals that includes it. A `--` left alone after the last option, with no
positional left to take it, is reported as "unrecognized". troupe's scan treats it as a separator that guards
nothing, so the check passes. Python 3.12.0, 3.12.14, 3.13, 3.14 and 3.15 all behave the same way, so this isn't a
version quirk.

## What Changes

- **Decision (the issue's "To decide"): a separator with nothing after it is accepted and changes nothing.**
  `troupe status x --json --` parses exactly as `troupe status x --json` does. This matches the lines that already
  parse (`status x --`, `status --json --`, `logs abc --`). It's also not a guess: a `--` with nothing after it
  marks nothing as a value, so the line has one meaning. The alternative, refusing it with a new named code, would
  have to refuse `status x --` too to be consistent. That would break lines that work today and add an error that
  protects nothing. Design D1 sets out both.
- **The parser drops a trailing separator before argparse sees the line.** Only the `--` that the scan reads as the
  separator is dropped, and only when it is the last token. A `--` that comes after the separator is a value and is
  untouched (`status x -- --` is still `usage.extra-argument`). troupe's checks and argparse then agree on every
  line of this shape.
- **Tests pin it without depending on hypothesis.** A parametrised test covers the issue's argv and one line of the
  shape for each command (`status`, `logs`, `perform`, `echo`, `choose`). Each line must parse to the same namespace
  as the line without its trailing `--`. A new property test checks the general claim: for any generated line with
  no `--` in it, adding a trailing `--` gives the same outcome, either the same namespace or the same error code.
  The existing property test stays, and should no longer find this gap.
- **The cli spec states the rule**, as a scenario under the existing `--` requirement.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cli`: the requirement "Dash-leading values follow the `--` convention" gains the rule that a separator with
  nothing after it changes nothing, with scenarios for `troupe status x --json --` and a `--` that comes after
  the separator.

## Impact

- `packages/troupe/src/troupe/cli/parser.py`: the scan records where the separator is, and `parse` hands argparse
  the line without a trailing separator. The module docstring states the rule.
- `packages/troupe/tests/test_cli.py`: the deterministic tests and the new property test.
- `openspec/specs/cli/spec.md`, through the delta.
- No change to error codes, the protocol's error schema, exit codes or stored data. Lines that parse today parse the
  same way. The only lines whose outcome changes are those that reach `usage.invalid` today, and they now parse.
- Out of scope: the other open cli issues (#73, #84).
