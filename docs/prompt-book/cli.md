---
title: CLI
description: Every command and option.
status: written
prerelease: false
---

The command line is a thin client. Every command it offers is a command or query in troupe's core, which the run
server and UIs will also call, so nothing here behaves differently from any other surface.

Pre-alpha. The conventions below apply to every subcommand.

## Commands

Every command runs in a **theatre**: the nearest directory, from where you are upwards, that holds `.troupe/`.
troupe never creates one for you; without one, a command fails with `theatre.not-found`.

- **`troupe perform`** runs one actor, as config defines it, and records the run. Progress goes to standard error;
  on success, standard output gets `run <id> succeeded`. It exits by the run's outcome: 0 succeeded, 130 cancelled
  with Ctrl-C, 1 otherwise.
- **`troupe status`** lists the most recent runs, newest first, or shows one run.
- **`troupe logs`** shows a run's events in order; `--follow` waits for more until the run ends.
- **`troupe diff`** shows what a run in its own worktree changed, as git's binary diff, byte for byte, so you can
  pipe it to `git apply`.
- **`troupe accept`** applies a worktree run's changes to your files, unstaged, all or nothing, then removes its
  worktree. If they don't apply cleanly it changes nothing and names the files.
- **`troupe discard`** removes a worktree run's worktree. It removes files, not git state: branches, tags, stashes,
  config or hooks the run made stay.
- **`troupe config set`**, **`config unset`** and **`config get`** change and show config. Each change is recorded
  with who made it and why (`--reason`), and troupe writes the files under `.troupe/` from config.
- **`troupe flush`** makes the config files exactly what config says. Every command that uses config does it first.

A run is named by its full id or by its first 8 or more characters. [Performances and
runs](../the-company/performances-and-runs.md) describes runs, their states and what is recorded.

**`perform` names an actor, and config says the rest:** its runner (`scripted` is the only one so far), the
runner's options, its effect check (`expect`: the files a run must create or change, relative to the theatre's
root, where `[]` means no check), its character and its workspace. `--direction` says what this run is asked to do.

**A run works in its own git worktree** by default, made from your latest commit: your files change only when you
`troupe accept` it. An actor with `workspace: theatre` works in your files directly instead. See
[Workspaces](../the-company/performances-and-runs.md#workspaces).

**A config value on the command line is typed by its schema.** A string field takes the text as given, a number or
boolean is parsed strictly (`true`, never `yes`), and a list or a group is JSON. `<path>=@<file>` reads a value
from a file: a string field gets the file's text exactly, anything else the file's JSON or YAML.

**`--rehearse`** on any command that changes anything runs its checks, shows what it would do, and changes nothing.
It exits 3 when it would change something, 0 when there's nothing to do, and with the refusal's own code when the
command would be refused.

The local stage runs an actor only when policy allows it (`TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`; see
[Policy](../the-company/performances-and-runs.md#policy)).

```text
troupe config set actors.tester.runner=scripted actors.tester.options=@hello.json 'actors.tester.expect=["out/hello.txt"]'
troupe perform tester --direction "write the hello file"
troupe logs 1a2b3c4d --follow        # from another terminal, while it runs
troupe status 1a2b3c4d
troupe diff 1a2b3c4d | less
troupe accept 1a2b3c4d --reason "looks right"
```

**Ctrl-C** during `perform` cancels the run, records it as `cancelled`, and exits 130. Pressing it again only says
troupe is already cancelling: the run is stopped within its grace period either way.

**`--json`** on `status`, `logs` and `diff` prints the query's result exactly in its protocol shape
([`protocol/schemas/client/`](https://github.com/troupe-run/troupe/tree/main/protocol/schemas/client/)). With
`--follow`, each update is printed on its own line first.

<!-- generated: cli (from troupe.cli.COMMANDS and the global options; regenerate with `uv run scripts/docs_reference.py`) -->
### `troupe perform`

Run one actor and record the run.

```text
troupe perform <actor> [--direction <direction>] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<actor>` | Yes | The actor's name, as config defines it |
| `--direction <direction>` | No | What the actor is asked to do in this run |
| `--rehearse` | No | Run every check and start nothing: show what would run |

### `troupe status`

Show the most recent runs, or one run.

```text
troupe status [<run>] [--limit <limit>] [--json]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | No | A run's id, or at least its first 8 characters |
| `--limit <limit>` | No | How many runs to list, newest first |
| `--json` | No | Print the result as JSON |

### `troupe logs`

Show a run's events in order.

```text
troupe logs <run> [--follow] [--json]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | Yes | A run's id, or at least its first 8 characters |
| `--follow` | No | Wait for new events until the run ends |
| `--json` | No | Print updates and the result as JSON |

### `troupe diff`

Show the changes a worktree run captured.

```text
troupe diff <run> [--json]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | Yes | A run's id, or at least its first 8 characters |
| `--json` | No | Print the result as JSON |

### `troupe accept`

Apply a worktree run's changes to your files, unstaged, all or nothing.

```text
troupe accept <run> [--reason <reason>] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | Yes | A run's id, or at least its first 8 characters |
| `--reason <reason>` | No | Why, recorded in the lineage |
| `--rehearse` | No | Check that the changes apply cleanly and name the files, changing nothing |

### `troupe discard`

Remove a worktree run's worktree, keeping nothing it wrote. It removes files, not git state: branches, tags, stashes, config, hooks or pushes the run made in git stay.

```text
troupe discard <run> [--reason <reason>] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | Yes | A run's id, or at least its first 8 characters |
| `--reason <reason>` | No | Why, recorded in the lineage |
| `--rehearse` | No | Name the worktree that would be removed, removing nothing |

### `troupe config set`

Set config values, as one change.

```text
troupe config set <path=value> [--reason <reason>] [--json] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<path=value>` | Yes | A value to set, such as actors.tester.runner=scripted; path=@file reads it from a file |
| `--reason <reason>` | No | Why, recorded with the change |
| `--json` | No | Read every value as JSON, whatever its schema says |
| `--rehearse` | No | Change nothing: show what would be recorded and written |

### `troupe config unset`

Remove config values or groups, as one change.

```text
troupe config unset <path> [--reason <reason>] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<path>` | Yes | A value or a group to remove, such as actors.tester |
| `--reason <reason>` | No | Why, recorded with the change |
| `--rehearse` | No | Change nothing: show what would be recorded and written |

### `troupe config get`

Show config, or the value or group at a path.

```text
troupe config get [<path>] [--json]
```

| Argument | Required | What it is |
|---|---|---|
| `<path>` | No | A value or group, such as actors.tester |
| `--json` | No | Print the result as JSON |

### `troupe flush`

Make the config files exactly what config says.

```text
troupe flush [--force] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `--force` | No | Replace files troupe didn't write too, keeping a copy of each |
| `--rehearse` | No | Change nothing: show what would be written |

### Global flags

| Flag | What it does |
|---|---|
| `--version` | Show the version, and the protocol version it carries |
| `-h`, `--help` | Show this help |
<!-- end generated: cli -->

`--version` prints troupe's version and the version of the
[protocol](https://github.com/troupe-run/troupe/tree/main/protocol) it carries, such as
`troupe 0.4.0 (protocol 0.2.1)`. It needs no theatre, identity or daemon. Global flags work anywhere on the line,
before or after the subcommand. Flags can't be abbreviated: `--vers` is an unknown flag, not `--version`.

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
$ troupe perform
troupe: `troupe perform` needs <actor>.
  fix: Run `troupe perform --help` to see its options.
```

Behind the text, each error is structured data with a stable `code` (for example `usage.unknown-command`), the problem,
the fix, and an optional path and details. Its shape is defined once, in
[`protocol/schemas/error.schema.json`](https://github.com/troupe-run/troupe/blob/main/protocol/schemas/error.schema.json),
which lists every code with what its details hold, so other surfaces can show the same error in their own words.

## Exit codes

Every exit code `troupe` can return. When a command fails, standard output is empty and standard error says what
went wrong and how to fix it.

<!-- generated: exit-codes (from troupe.core.exit_codes.ExitCode; regenerate with `uv run scripts/docs_reference.py`) -->
| Code | Name | Meaning |
|---|---|---|
| 0 | `OK` | The command completed. |
| 1 | `FAILURE` | The command could not complete. The error says why and what to do. |
| 2 | `USAGE` | The command line was not understood: an unknown command or flag, or a malformed value. |
| 3 | `WOULD_CHANGE` | A rehearsal (`--rehearse`) found that the command would succeed and change something: record a change, write a file, or start a run. A rehearsal with nothing to do exits 0, and one that would be refused exits with the refusal's own code, so CI can tell the three apart. |
| 130 | `CANCELLED` | You cancelled the command with Ctrl-C, and it stopped cleanly: `troupe perform` records the run as `cancelled`. 130 is the shell's code for an interrupt (128 + SIGINT), and troupe uses it on every platform. |
<!-- end generated: exit-codes -->
