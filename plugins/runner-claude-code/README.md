# troupe-runner-claude-code

An actor runner for troupe that runs [Claude Code](https://code.claude.com). It speaks the
[runner contract](../../contributing/runners.md) over standard input and output, uses only the standard library, and
imports nothing from troupe.

```console
python -m troupe_runner_claude_code
```

## Options

Every option is optional. Any other option is refused, with an error naming it, and so is a value of the wrong
shape. No option names a program to run.

| Option | What it is |
|---|---|
| `model` | The model Claude Code uses, passed as `--model`. Absent: Claude Code's own default. It can't start with `-` |
| `maxBudgetUsd` | The most a run may spend, in US dollars, above 0, passed as `--max-budget-usd`. Absent: USD 5 |
| `permissionMode` | `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk` or `plan`, passed as `--permission-mode`. Absent: Claude Code's own default, which in print mode denies edits and any tool not allowed |
| `allowedTools` | Permission rules that allow a tool, such as `Read` or `Bash(git status)` |
| `disallowedTools` | Permission rules that deny a tool |
| `settingSources` | The Claude Code setting sources to load: any of `user`, `project` and `local`. Absent: none |

A run always has a budget, so a runaway loop stops. The runner never grants more than config asks for: without
`permissionMode` and `allowedTools`, Claude Code can read but not write, and the runner reports each denied tool as
a `log` warning before the result. An actor that writes files needs, for example:

```yaml
options:
  permissionMode: acceptEdits
  allowedTools: ["Bash(uv run pytest *)"]
```
