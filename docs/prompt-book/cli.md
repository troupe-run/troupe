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

Every command but `init` runs in a **theatre**: the nearest directory, from where you are upwards, that holds
`.troupe/`. `troupe init` makes one; without one, every other command fails with `theatre.not-found`.

- **`troupe init`** makes a theatre in the directory you're in, which must be in a git repository and have no
  theatre in it or above it. It writes `.troupe/.gitignore` and `.troupe/.gitattributes`, and without `--audition`
  records nothing. `--audition` also defines a working example actor, `lead`, recorded as a config change, and
  prints what to run next: commit, allow the local stage, and `troupe perform lead` with an example direction. The
  actor runs Claude Code, with a USD 1 budget and a character in `.troupe/actors/lead.md`, which you change by
  editing the file. `--runner` gives it another runner: `anthropic`, `claude-code`,
  `mistralrs`, `ollama`, `openai` or `scripted`, which runs offline with no account. A runner that comes as an
  [extra](../opening-night/install.md#runners-that-come-as-extras) and isn't installed is refused with
  `runner.not-installed`, naming the extra. For `mistralrs`, `init` then prepares the runner's engine, so the first
  run starts quickly. The notice `runner.warming-up` says it has started; then `runner.warmed-up` says it's done,
  `runner.warm-up-cut-off` that it took longer than two minutes and the first run will finish it, or
  `runner.warm-up-failed` why the runner can't run here.
- **`troupe perform`** runs one actor, as config defines it, and records the run as the one step of a new
  performance. Progress goes to standard error, starting with the performance's id and then the run's; on success,
  standard output gets `performance <id>: run <id> succeeded`, and when a run fails, standard error gets why, with
  its id. Wherever a command takes a run, its performance's id works too. It exits by the run's outcome: 0
  succeeded, 130 cancelled with Ctrl-C, 1 otherwise.
- **`troupe status`** lists the most recent performances, newest first, each line starting with the performance's
  id and then its run's first 8 characters, with its cost when it has one, or shows one run, with its performance,
  the tokens it used and its cost, what the audit of its changes found beside its outcome, and the notices troupe
  raised while it went. A cost says whether the service reported it or it's estimated from the runtime's
  price (`~$0.0136, estimated`); a figure the runner didn't report isn't shown.
- **`troupe logs`** shows a run's events and the notices troupe raised while it went, in order, with the tokens and
  cost on the result's line, then its outcome and its audit; `--follow` waits for more until the run ends.
- **A run keeps the name its actor ran under.** When the actor has been renamed since (`troupe config mv`, or its
  files moved by hand), `troupe status` shows it as `tester (now qa)`, following every rename to the name it has
  now, and `troupe logs` adds the line `actor: tester (now qa)` after the outcome. `troupe perform tester` after the
  rename is refused, and its fix names `qa`.
- **`troupe diff`** shows what a run in its own worktree changed, as git's binary diff, byte for byte, so you can
  pipe it to `git apply`.
- **`troupe approve`** and **`troupe reject`** answer a run that waits at its gate. Approve keeps its changes:
  it applies them to your files, unstaged, all or nothing, and records your approval. Reject removes its worktree.
  Accept and discard are refused for such a run, and name these instead.
- **`troupe accept`** applies the changes of a worktree run that reached no gate (one that didn't succeed) to your
  files, unstaged, all or nothing, then removes its worktree. If they don't apply cleanly it changes nothing and
  names the files.
- **`troupe discard`** removes a worktree run's worktree. It removes files, not git state: branches, tags, stashes,
  config, hooks or pushes the run made stay.
- **`troupe config set`**, **`config unset`** and **`config get`** change and show config. Each change is recorded
  with who made it and why (`--reason`), and troupe writes the files under `.troupe/` from config.
- **`troupe config mv`** renames a whole actor, runtime or flow, such as `troupe config mv actors.tester actors.qa`,
  as one change. Its files move as they are, a runtime's actors and an actor's flows are pointed at its new name in
  the same change, and changes made to the old name on another branch follow it when the branches merge. It's refused
  for anything but a whole actor, runtime or flow, a name config doesn't hold, a new name config already holds, and a
  built-in runtime's name. If you've already moved the files by hand, it records the rename and writes only what the
  rename changes: a runtime's actors' `runtime` lines, or an actor's flows' steps.
- **`troupe sync`** records your hand edits to the config files, each as a change by an unknown author, then makes
  every file say what config says. Every command that uses config does it first. `--rehearse` shows what it would
  record and write; `--force` replaces a file troupe can't read as config, keeping a copy.
- **`troupe config drop`** and **`config keep`** answer the notice `config.edit-abandoned`, which says a file you
  edited is back to what it was. `drop` removes the changes that left behind, if nothing has used them yet; `keep`
  keeps them and stops troupe asking. [Undoing an edit](../stagecraft/hand-edit-config.md#undoing-an-edit) says
  when each works.

A run is named by its full id, its performance's, or the first 8 or more characters of either. [Performances and
runs](../the-company/performances-and-runs.md) describes runs, their states and what is recorded.

**`perform` names an actor, and config says the rest:** its runner (`anthropic`, `claude-code`, `mistralrs`,
`ollama`, `openai` or `scripted`), the runner's options, the runtime and model it uses, if its runner takes one, its
effects, its effect check (`expect`: the files a run must create or change, relative to the theatre's root, where
`[]` means no check), its character, its workspace, what it does when its context is full (`onContextFull`), and its
approvers.
`--direction` says what this run is asked to do. [Point actors at a service](../stagecraft/runtimes.md) says how a
runtime is chosen and set.

**A run works in its own git worktree** by default, made from your latest commit: your files change only when its
work is kept at its gate, by troupe when it applies cleanly, or by `troupe approve` when it waits for you. `perform`
exits 4 when the run succeeded and its work waits. An actor with `workspace: theatre` works in your files directly
instead. See [Workspaces](../the-company/performances-and-runs.md#workspaces) and
[Gates](../the-company/gates-and-decisions.md).

**A config value on the command line is typed by its schema.** A string field takes the text as given, a number or
boolean is parsed strictly (`true`, never `yes`), and a list or a group is JSON. `<path>=@<file>` reads a value
from a file: a string field gets the file's text exactly, anything else the file's JSON or YAML.

**A config path is keys joined by dots, and any key can be written in square brackets.** Nothing inside brackets
splits, so a key that holds a dot, such as a model's name, goes in them: `runtimes.openai.prices[gpt-4.1].input`.
Inside brackets, `\]` is a `]` and `\\` is a `\`. A key that holds `=` goes in brackets too, since `config set`
reads the path up to the first `=` outside them. Every config command reads paths this way, and troupe shows them
this way, so a path in its output or in an error can be typed back as it is. Brackets were chosen over quotes or
backslashes because no shell drops them without saying so. In zsh an unquoted `[` starts a pattern and stops the
command with "no matches found", so quote the argument there:

```text
troupe config unset 'runtimes.openai.prices[gpt-4.1]'
```

A backslash outside brackets (`gpt-4\.1`) is refused rather than read, as is an unclosed `[` or an empty key, with
`config.path-malformed` naming where it went wrong and the text up to there, never what follows, which in `config set`
can be the value.

**`--rehearse`** on any command that changes anything runs its checks, shows what it would do, and changes nothing.
It exits 3 when it would change something, 0 when there's nothing to do, and with the refusal's own code when the
command would be refused.

The local stage runs an actor only when policy allows it (`TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true`; see
[Policy](../the-company/performances-and-runs.md#policy)).

```text
troupe config set actors.tester.runner=scripted actors.tester.options=@hello.json 'actors.tester.expect=["out/hello.txt"]' 'actors.tester.effects.write=["out/**"]'
troupe perform tester --direction "write the hello file"
troupe logs 1a2b3c4d --follow        # from another terminal, while it runs
troupe status 1a2b3c4d
troupe diff 1a2b3c4d | less
troupe approve 1a2b3c4d --reason "looks right"   # when it waits at its gate
```

**Ctrl-C** during `perform` cancels the run, records it as `cancelled`, and exits 130. Pressing it again only says
troupe is already cancelling: the run is stopped within its grace period either way.

**`--json`** on `status`, `logs`, `diff` and `config get` prints the query's result exactly in its protocol shape
([`protocol/schemas/client/`](https://github.com/troupe-run/troupe/tree/main/protocol/schemas/client/)). With
`--follow`, each update is printed on its own line first.

<!-- generated: cli (from troupe.cli.COMMANDS and the global options; regenerate with `uv run scripts/docs_reference.py`) -->
### `troupe init`

Make a theatre here, and with --audition, a working example actor.

```text
troupe init [--audition] [--runner <runner>] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `--audition` | No | Also define a working example actor, lead (Claude Code unless --runner says) |
| `--runner <runner>` | No | The example actor's runner, such as scripted (only with --audition) |
| `--rehearse` | No | Run every check and make nothing: show what would be made |

### `troupe perform`

Run one actor and record the run, as a new performance.

```text
troupe perform <actor> [--direction <direction>] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<actor>` | Yes | The actor's name, as config defines it |
| `--direction <direction>` | No | What the actor is asked to do in this run |
| `--rehearse` | No | Run every check and start nothing: show what would run |

### `troupe status`

Show the most recent performances, or one run.

```text
troupe status [<run>] [--limit <limit>] [--json]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | No | A run's id, or its performance's, or at least the first 8 characters of either |
| `--limit <limit>` | No | How many performances to list, newest first |
| `--json` | No | Print the result as JSON |

### `troupe logs`

Show a run's events and notices in order.

```text
troupe logs <run> [--follow] [--json]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | Yes | A run's id, or its performance's, or at least the first 8 characters of either |
| `--follow` | No | Wait for new events and notices until the run ends |
| `--json` | No | Print updates and the result as JSON |

### `troupe diff`

Show the changes a worktree run captured.

```text
troupe diff <run> [--json]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | Yes | A run's id, or its performance's, or at least the first 8 characters of either |
| `--json` | No | Print the result as JSON |

### `troupe accept`

Apply a worktree run's changes to your files, unstaged, all or nothing.

```text
troupe accept <run> [--reason <reason>] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | Yes | A run's id, or its performance's, or at least the first 8 characters of either |
| `--reason <reason>` | No | Why, recorded in the lineage |
| `--rehearse` | No | Check that the changes apply cleanly and name the files, changing nothing |

### `troupe discard`

Remove a worktree run's worktree, keeping nothing it wrote. It removes files, not git state: branches, tags, stashes, config, hooks or pushes the run made in git stay.

```text
troupe discard <run> [--reason <reason>] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | Yes | A run's id, or its performance's, or at least the first 8 characters of either |
| `--reason <reason>` | No | Why, recorded in the lineage |
| `--rehearse` | No | Name the worktree that would be removed, removing nothing |

### `troupe approve`

Answer a run's open cue by approving its changes: apply them to your files, unstaged, all or nothing, and record your approval.

```text
troupe approve <run> [--reason <reason>] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | Yes | A run's id, or its performance's, or at least the first 8 characters of either |
| `--reason <reason>` | No | Why, recorded in the lineage |
| `--rehearse` | No | Check the cue is open and the changes apply cleanly, and name the files, changing nothing |

### `troupe reject`

Answer a run's open cue by rejecting its changes: remove its worktree, keeping nothing it wrote, and record why. It removes files, not git state.

```text
troupe reject <run> [--reason <reason>] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<run>` | Yes | A run's id, or its performance's, or at least the first 8 characters of either |
| `--reason <reason>` | No | Why, recorded in the lineage |
| `--rehearse` | No | Name the worktree that would be removed, removing nothing |

### `troupe config set`

Set config values, as one change.

```text
troupe config set <path=value> [--reason <reason>] [--json] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<path=value>` | Yes | A value to set, such as actors.tester.runner=scripted; path=@file reads it from a file. A key that holds a dot goes in brackets: prices[gpt-4.1] |
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
| `<path>` | Yes | A value or a group to remove, such as actors.tester. A key that holds a dot goes in brackets: prices[gpt-4.1] |
| `--reason <reason>` | No | Why, recorded with the change |
| `--rehearse` | No | Change nothing: show what would be recorded and written |

### `troupe config mv`

Rename an actor or runtime, as one change, keeping its history.

```text
troupe config mv <old> <new> [--reason <reason>] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<old>` | Yes | The actor or runtime, such as actors.tester |
| `<new>` | Yes | Its new name, such as actors.qa |
| `--reason <reason>` | No | Why, recorded with the change |
| `--rehearse` | No | Change nothing: show what would be recorded and written |

### `troupe config get`

Show config, or the value or group at a path.

```text
troupe config get [<path>] [--json] [--resolved]
```

| Argument | Required | What it is |
|---|---|---|
| `<path>` | No | A value or group, such as actors.tester. A key that holds a dot goes in brackets: prices[gpt-4.1] |
| `--json` | No | Print the result as JSON |
| `--resolved` | No | Show runtimes as troupe resolves them, from its built-in ones, config and your environment, each value with where it came from |

### `troupe config drop`

Drop an abandoned edit: remove the changes a file going back left behind.

```text
troupe config drop <change> [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<change>` | Yes | The change id the notice about the abandoned edit names |
| `--rehearse` | No | Change nothing: show what would be dropped |

### `troupe config keep`

Keep an abandoned edit's changes, and stop troupe asking about them.

```text
troupe config keep <change> [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `<change>` | Yes | The change id the notice about the abandoned edit names |
| `--rehearse` | No | Change nothing: show what would be kept |

### `troupe sync`

Record hand edits to the config files, and make every file say what config says.

```text
troupe sync [--force] [--rehearse]
```

| Argument | Required | What it is |
|---|---|---|
| `--force` | No | Replace files troupe can't read as config, keeping a copy of each |
| `--rehearse` | No | Change nothing: show the hand edits it would record and the files it would write |

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
| 4 | `WAITING` | `troupe perform`'s run succeeded, and its work waits at its gate for a role's answer: see it with `troupe diff`, then `troupe approve` or `troupe reject` it. Its changes aren't in your files yet, so a script that goes on only once the work is kept can tell. |
| 130 | `CANCELLED` | You cancelled the command with Ctrl-C, and it stopped cleanly: `troupe perform` records the run as `cancelled`. 130 is the shell's code for an interrupt (128 + SIGINT), and troupe uses it on every platform. |
<!-- end generated: exit-codes -->
