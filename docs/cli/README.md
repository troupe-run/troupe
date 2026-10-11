# The `troupe` command line

The command line is a thin client. Every command it offers is a command or query in troupe's core, which the run
server and UIs will also call, so nothing here behaves differently from any other surface.

Pre-alpha: there are no subcommands yet, only the conventions below. They apply to every subcommand as it is
added.

## Global flags

| Flag | What it does |
|---|---|
| `--version` | Prints the installed version. Needs no theatre, identity or daemon. |
| `-h`, `--help` | Prints help: for troupe, or for the subcommand it follows. |

Global flags work anywhere on the line, before or after the subcommand. Flags can't be abbreviated: `--vers` is
an unknown flag, not `--version`.

## Values that start with `-`

A value that starts with `-` (such as `-5` or `-.inf`) has to come after `--`. Without it, troupe can't tell a
value from an option, so it refuses rather than guessing:

```console
$ troupe -5
troupe: `-5` starts with `-`, so it is read as an option, not a value.
  fix: Put `--` before values that start with `-`, for example `-- -5`.
```

## Errors

Every error names the problem and the fix, and the path when one is involved. Errors go to standard error, and
standard output stays empty, so a failing command never prints something that looks like a result.

```console
$ troupe verison
troupe: `verison` is not a troupe command.
  fix: Did you mean `--version`?
```

```console
$ troupe --bogus
troupe: `--bogus` is not a troupe option.
  fix: Run `troupe --help` to see the commands and options. If `--bogus` is a value, put `--` before it.
```

Behind the text, each error is structured data with a stable `code` (for example `usage.unknown-command`), the
problem, the fix, and an optional path and details. Its shape is defined once, in
[`protocol/schemas/error.schema.json`](../../protocol/schemas/error.schema.json), so other surfaces can show the
same error in their own words.

The exit codes are listed in [exit-codes.md](exit-codes.md).
