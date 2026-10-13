# Design

## Context

See proposal.md for why. What exists on main (69d6c27), all in `packages/troupe/src/troupe/cli/parser.py`:

- `parse` builds a root parser and one subparser per `Command`, each configured by the command's own
  `configure(parser)` callback (design D2 of bootstrap-repo: argparse does the parsing).
- `_prescan` walks argv first. It finds the chosen command, refuses unknown commands, unknown flags and unseparated
  dash-leading values with structured errors (no prefix in their problems), and records which option destinations
  were given. It assumes an option takes zero or one value: when one takes a value, it skips the next token.
- Everything else is argparse's. With `exit_on_error=False`, Python 3.12 raises `ArgumentError` from a subparser for
  missing arguments, required groups, conflicts and bad types; these reach the root's `parse_args` and are wrapped as
  `usage.invalid` with `problem=f"troupe: {error}"`. Extra positionals are reported by the root's `error()`, wrapped
  with `f"{self.prog}: {message}"`. Both use `HELP_FIX`, which points at `troupe --help`.
- `render_error` (`cli/render.py`) prefixes every problem with `troupe: `. That is the only place a prefix belongs.
- The commands that declare arguments today: `perform` (positional `actor`; required `--runner`; `--runner-options`,
  `--instructions`; a required exclusive group of `--expect` (append) and `--no-effect-check`), `status` (optional
  positional `run`; `--limit` with `type=int`; `--json`) and `logs` (positional `run`; `--json` and one more flag).
- CI runs Python 3.12 and 3.13. argparse's message wording differs between versions and is translated by gettext.

## Goals / Non-Goals

**Goals:**
- One structured error per usage shape, with stable wording that troupe owns, the same on every Python version.
- The pre-scan and the new check are the CLI's judgement of a command line; argparse only converts a line they have
  accepted into a namespace.

**Non-Goals:**
- Replacing argparse, or changing how commands declare arguments (`Command.configure` stays).
- Reporting several usage problems at once. One error per invocation, as today.
- Changing the dash-value convention for option values: `--limit -5` still reaches argparse as a value, as today.
- Command-level validation inside a command's `run` (such as `status <run> --limit 2`, which the core refuses with
  its own code). Those errors already name their problem without a prefix.

## Decisions

### D1. troupe checks the shapes itself, from the declared arguments, before argparse runs

After the pre-scan has chosen a command, a check compares what the line gave with what the command declared, and
raises the first problem it finds as a structured error. argparse then parses a line the check has accepted.

Alternatives:
- **Strip the prefix, name the command and point at its help, but keep argparse's message.** It fixes the three
  bullets of #53 with least code, but the problem stays unstructured English that changes with the Python version,
  and `usage.invalid` stays a single code nothing can phrase differently. The issue's expected text
  (`needs one of --expect or --no-effect-check`) isn't argparse's wording, so this wouldn't produce it.
- **Reword argparse's messages by matching them.** Fragile: the strings change between versions and are translated
  through gettext. A missed match would fall through to the backstop silently.
- **Catch `ArgumentError` and read its structure.** Only partly possible: missing arguments and required groups are
  raised with `argument_name=None`, so the structure isn't there.

The check is the same pattern the pre-scan already uses for unknown flags, and lives next to it.

### D2. The order of checks, so one line gives one predictable error

The scan and check walk the line once; problems are reported in this order:

1. The pre-scan's own errors, in the order it meets the tokens (unchanged): unknown command, unknown flag, dash value.
2. `usage.missing-value`: an option that takes a value is the last token, or is followed by `--` or by a token that
   looks like a flag (`_looks_like_a_flag`). The pre-scan no longer swallows that token as the value.
3. `usage.conflicting-options`: two different options of one exclusive group were given. The same option given twice
   (`--expect a --expect b`) is not a conflict.
4. `usage.extra-argument`: more positional values than the command's positionals take; the first value that has no
   place is named. Values after `--` are positionals.
5. `usage.missing-argument`: required options, then required positionals, in declaration order.
6. `usage.missing-one-of`: a required exclusive group with none of its options given.
7. `usage.invalid-value`: a value that its argument's `type` rejects (`ValueError`, `TypeError` or
   `ArgumentTypeError`, as argparse treats them) or that isn't one of its `choices`.

What was typed wrong comes before what is missing, and missing things come in the order the help lists them, so
`troupe perform tester` asks for `--runner` before the effect check.

### D3. The check converts values itself, so `invalid-value` can name the value

The check calls the argument's `type` on the raw value it recorded, and checks `choices`, so the error carries the
command, the argument and the exact value. argparse converts the same value again when it parses; for the plain
converters troupe uses (`int`, `str`) that is harmless. A command whose argument type has a side effect (such as
`argparse.FileType`) would run it twice; `_declared` refuses such a type as an internal error rather than allowing it
quietly, and none exists today.

### D4. Reading argparse's declarations happens in one place

The check needs each command's options, positionals (with `nargs`) and exclusive groups. argparse keeps these in
private attributes (`_option_string_actions`, `_actions`, `_mutually_exclusive_groups`). `_options_of` is already
"the one place troupe reads it"; it becomes `_declared(parser)`, returning a small troupe-owned, frozen description
of the command's arguments, and nothing else touches argparse's internals. A test pins `_declared` against the real
`perform`, `status` and `logs`, so a Python upgrade that moves the internals fails that test by name.

`_declared` also refuses declarations the scan can't read correctly, rather than guessing: an option whose `nargs` is
not zero or one value, or a positional `nargs` other than one, `?`, `*`, `+` or an integer. These raise
`internal.unexpected` at parse time; no command declares them today.

Alternative: commands declare arguments in a troupe-owned structure instead of an argparse callback. Cleaner, but it
touches every command and the run server's future surface for no gain this fix needs. It stays open for later.

### D5. Problems and fixes are worded in one place

Each code has one function that builds its `TroupeError`, next to `_unknown_flag` and the others. The command is
named as people type it (`troupe perform`); options as written (`--runner`); positionals by their metavar or
destination in angle brackets (`<run>`). Problems:

| Code | Problem |
|---|---|
| `usage.missing-argument` | `` `troupe perform` needs --runner. `` / `` `troupe logs` needs <run>. `` |
| `usage.missing-one-of` | `` `troupe perform` needs one of --expect or --no-effect-check. `` |
| `usage.conflicting-options` | `` `troupe perform` takes --expect or --no-effect-check, not both. `` |
| `usage.extra-argument` | `` `troupe status` got an extra value, `two`. `` |
| `usage.missing-value` | `` `troupe status` needs a value after --limit. `` |
| `usage.invalid-value` | `` `troupe status` can't use `notanumber` for --limit. `` |
| `usage.invalid` | `` `troupe perform`: <argparse's message> `` (or the message alone, before a command) |
| `usage.unknown-flag` | `` `--bogus` is not an option of `troupe status`. `` (unchanged before a command) |

The fix is `Run \`troupe <command> --help\` to see its options.` after a command is chosen, and the existing
`HELP_FIX` before one. `usage.missing-value` and `usage.extra-argument` add the dash hint where it applies ("If the
value starts with `-`, write `--limit=<value>`" and "If it was meant as a value, check the command takes one").
`usage.unknown-flag` keeps its suggestion and `--` hint.

### D6. Details name the command by its name; the schema closes every shape

`details.command` is the command's name (`perform`), not the rendered `troupe perform`: the program name is the
surface's to add. Shapes:

| Code | Details |
|---|---|
| `usage.missing-argument` | `command`, `argument` (`--runner`, or the positional's destination `run`) |
| `usage.missing-one-of` | `command`, `options` (two or more option strings) |
| `usage.conflicting-options` | `command`, `options` (the two given) |
| `usage.extra-argument` | `command`, `value` |
| `usage.missing-value` | `command`, `option` |
| `usage.invalid-value` | `command`, `argument`, `value` |
| `usage.invalid` | `command` (string or null) |
| `usage.unknown-flag` | `flag`, `suggestion`, and now `command` (string or null) |

All are closed objects with typed values, per the `protocol` spec, and catalogued in `CODES` with
`ExitCode.USAGE`, so the existing both-ways catalogue test covers them.

### D7. `usage.invalid` stays, as the backstop

If argparse still refuses a line the check accepted, that is a gap in the check, but the person must still get a
structured, prefix-free error that names the command and exits 2. The two argparse paths (`ArgumentError` out of
`parse_args`, and `_Parser.error`) both build `usage.invalid` without a prefix. `_Parser.error` can't know the chosen
command, so it raises an internal marker that `parse` turns into `usage.invalid` with the command it chose. A test
reaches the backstop through a test command whose argument uses a custom action that fails in argparse only.

## Risks / Trade-offs

- [The check and argparse disagree on a line] → argparse still runs after the check, so a line the check wrongly
  accepts is refused as `usage.invalid` (never a success with bad arguments). A property test generates command lines
  over the test commands' declared arguments and asserts every refusal is one structured usage code, exit 2, with no
  prefix, and every acceptance parses.
- [A Python version moves argparse's private attributes] → confined to `_declared`, and pinned by its test (D4); CI
  runs 3.12 and 3.13.
- [Converting a value twice] → harmless for the converters troupe uses; side-effecting types are refused (D3).
- [Changing `usage.unknown-flag` and `usage.invalid` details] → breaks a reader of the old shape; nothing outside
  this repo reads them, and the protocol is pre-1.0.

## Migration Plan

None beyond the schema change: no stored data holds usage errors, and exit codes don't change.
