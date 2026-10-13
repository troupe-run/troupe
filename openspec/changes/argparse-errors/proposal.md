# Proposal

Issue: troupe-run/troupe#53. Surfaced by `perform`, `status` and `logs` (#36, PR #52), the first commands with
required arguments, a one-of group and typed values.

## Why

Every usage error argparse reports, rather than troupe's pre-scan, comes out wrong in three ways:

```console
$ troupe perform tester --runner scripted
troupe: troupe: one of the arguments --expect --no-effect-check is required
  fix: Run `troupe --help` to see the commands and options.
```

- **The prefix is doubled.** `troupe/cli/parser.py` puts a surface prefix into the problem
  (`f"{self.prog}: {message}"` in `_Parser.error`, `f"troupe: {error}"` for an `ArgumentError`), and
  `render_error` adds `troupe: ` again. A prefix in the problem also breaks the rule that errors are structured data
  each surface phrases for itself: a run server or UI showing this problem would show `troupe:` inside it.
- **It doesn't say which command was misused.** The prog is the root parser's (`troupe`), because errors from a
  subcommand reach the root as an `ArgumentError` (Python 3.12+ raises one for missing arguments when
  `exit_on_error=False`), or are reported by the root's own `error` (extra arguments).
- **The fix points at the root help** (`troupe --help`), not the command's (`troupe perform --help`).

Reproduced on `main` at 69d6c27, Python 3.12.14, for six shapes: a missing one-of group, a missing required option,
a missing positional, both options of an exclusive group, an extra positional, and a value of the wrong type; a
seventh, an option with no value (`--limit` last), reads `troupe: troupe: argument --limit: expected one argument`.
All exit 2, so only the text and the data are wrong.

There is a fourth, quieter problem: the text is argparse's English, which changes between Python versions (CI runs
3.12 and 3.13) and carries no structure. `usage.invalid` has no details, so another surface can't phrase it, and a
test can only match strings.

## What Changes

- **Usage problems carry no surface prefix.** The CLI adds `troupe: ` once, when it renders. This holds for every
  usage error, whoever detects it.
- **troupe checks what a command line is missing or has too much of itself**, from the chosen command's declared
  arguments, before argparse runs (design D1). Each shape gets its own code with details that name the command:
  - `usage.missing-argument`: a required option or positional wasn't given (`--runner`, `run`).
  - `usage.missing-one-of`: a required group got none of its options (`--expect` or `--no-effect-check`).
  - `usage.conflicting-options`: two options of an exclusive group were both given.
  - `usage.extra-argument`: more positional values than the command takes.
  - `usage.missing-value`: an option that takes a value is last, or is followed by another flag or `--`
    (`--limit --json`).
- **A value argparse can't convert is `usage.invalid-value`**, naming the command, the option or positional, and the
  value given (`--limit notanumber`).
- **`usage.invalid` stays as the backstop** for anything argparse reports that troupe's own checks didn't
  anticipate. Its problem names the command and carries argparse's message without a prefix, and it gains details
  naming the command. **BREAKING** for the error schema: `usage.invalid` had `details: false` (nothing outside this
  repo reads it).
- **Every usage error made after a command is chosen points its fix at that command's help**
  (`troupe perform --help`), and names the command in its problem. This includes the pre-scan's unknown-flag error
  inside a command, which today also points at `troupe --help`. Errors made before a command is chosen keep
  pointing at `troupe --help`. `usage.unknown-flag`'s details gain the command (or none, before one is chosen).

With this, the issue's example reads:

```console
$ troupe perform tester --runner scripted
troupe: `troupe perform` needs one of --expect or --no-effect-check.
  fix: Run `troupe perform --help` to see its options.
```

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cli`: usage errors carry no surface prefix, name the command they concern, point the fix at that command's help,
  and have a code for each shape (missing argument, missing one-of, conflicting options, extra argument, missing
  value, invalid value), with `usage.invalid` as the backstop.

The `protocol` requirement that every code is catalogued with its details is unchanged; the new codes are catalogued
under it.

## Impact

- `packages/troupe/src/troupe/cli/parser.py`: the pre-scan records positionals and option values; a post-scan
  check against the chosen command's declared arguments; prefix-free problems; command-aware help fixes.
- `packages/troupe/src/troupe/core/errors.py`: six new codes in `CODES`, all `ExitCode.USAGE`.
- `protocol/schemas/error.schema.json`: the new codes with closed details; `usage.invalid` and `usage.unknown-flag`
  gain the command in their details.
- Tests: `test_cli.py` (each shape through the real `perform`, `status` and `logs` and through test commands; the
  prefix appears once; the schema check over every usage shape), `test_cli_runs.py` where it asserts on usage text.
- Docs: `docs/cli/README.md` gains an example of a command's usage error.
- No new dependency; exit codes unchanged (all usage errors still exit 2).
