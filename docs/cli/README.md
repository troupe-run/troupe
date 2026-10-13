# The `troupe` command line

The command line is a thin client. Every command it offers is a command or query in troupe's core, which the run
server and UIs will also call, so nothing here behaves differently from any other surface.

Pre-alpha. The conventions below apply to every subcommand.

## Commands

Every command runs in a **theatre**: the nearest directory, from where you are upwards, that holds `.troupe/`.
troupe never creates one for you; without one, a command fails with `theatre.not-found`.

| Command | What it does |
|---|---|
| `troupe perform <actor>` | Runs one actor and records the run. Progress goes to standard error; on success, standard output gets `run <id> succeeded`. Exits by the run's outcome: 0 succeeded, 130 cancelled with Ctrl-C, 1 otherwise |
| `troupe status [<run>] [--limit <n>] [--json]` | Lists the most recent runs, newest first, or shows one run |
| `troupe logs <run> [--follow] [--json]` | Shows a run's events in order; `--follow` waits for more until the run ends |

A run is named by its full id or by its first 8 or more characters. [docs/runs.md](../runs.md) describes runs, their
states and what is recorded.

**`perform`'s flags are interim.** Until actors are configured, you say how to run one:

| Flag | |
|---|---|
| `--runner <name>` | Required. The runner, by name: `scripted` is the only one so far |
| `--runner-options <file>` | A JSON file holding the runner's options, passed to it untouched. For the scripted runner, `{"script": {...}}` or `{"scriptPath": "..."}` (relative to the theatre's root) |
| `--instructions <text>` | What the actor is asked to do |
| `--expect <path>` | A file the run must create or change, relative to where you are and inside the theatre. Repeatable |
| `--no-effect-check` | Check nothing after the run. One of `--expect` or this is required: there's no default |

The local stage runs an actor only when policy allows it (`TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`; see
[docs/runs.md](../runs.md#policy)).

```text
troupe perform tester --runner scripted --runner-options hello.json --expect out/hello.txt
troupe logs 1a2b3c4d --follow        # from another terminal, while it runs
troupe status 1a2b3c4d
```

**Ctrl-C** during `perform` cancels the run, records it as `cancelled`, and exits 130. Pressing it again only says
troupe is already cancelling: the run is stopped within its grace period either way.

**`--json`** on `status` and `logs` prints the query's result exactly in its protocol shape
([`protocol/schemas/client/`](../../protocol/schemas/client/)). With `--follow`, each update is printed on its own line
first.

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

A command's usage errors name the command and point at its own help:

```console
$ troupe perform tester --runner scripted
troupe: `troupe perform` needs one of --expect or --no-effect-check.
  fix: Run `troupe perform --help` to see its options.
```

Behind the text, each error is structured data with a stable `code` (for example `usage.unknown-command`), the
problem, the fix, and an optional path and details. Its shape is defined once, in
[`protocol/schemas/error.schema.json`](../../protocol/schemas/error.schema.json), which lists every code with what
its details hold, so other surfaces can show the same error in their own words.

The exit codes are listed in [exit-codes.md](exit-codes.md).
