# troupe-runner-claude-code

An actor runner for troupe that runs [Claude Code](https://code.claude.com). It speaks the
[runner contract](../../contributing/runners.md) over standard input and output, depends only on the
[plugin SDK](../../packages/troupe-plugin-sdk/README.md), and imports nothing else from troupe.

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
| `permissionMode` | `dontAsk` or `plan`, passed as `--permission-mode`. Absent: `dontAsk`. The modes that approve edits without a rule (`acceptEdits`, `auto`, `bypassPermissions`, `manual`) are refused: what Claude Code may change comes from the actor's effects |
| `allowedTools` | Permission rules that allow a tool, such as `Read` or `Bash(git status)`. A rule for an editing tool (`Edit`, `Write`, `NotebookEdit`, `MultiEdit`) or for `mcp__troupe` is refused |
| `disallowedTools` | Permission rules that deny a tool |
| `settingSources` | The Claude Code setting sources to load: any of `user`, `project` and `local`. Absent: none |

A run always has a budget, so a runaway loop stops. The runner never grants more than config asks for: what Claude
Code may change comes from the actor's [effects](#effects), and with none declared it can read but not write. The
runner reports each denied tool as a `log` warning before the result. An actor that edits its source and runs its
tests needs, for example:

```yaml
options:
  allowedTools: ["Bash(uv run pytest *)"]
effects:
  write: ["src/**", "tests/**"]
```

## Effects

The runner applies the actor's declared effects by translating them into Claude Code's own permission rules, and its
`init` event says so (`effects: translated`). It writes them into the settings file it already passes:

- **Claude Code runs in `dontAsk`** (or `plan`, when the options ask), which denies every tool call no rule allows.
- **Each `write` pattern becomes an allow rule,** `Edit(//<workspace>/<pattern>)`, which covers every built-in tool
  that edits a file. The rules are absolute, with a Windows drive written `//c/...`, as Claude Code reads them.
- **The workspace's `.git` and `.troupe`** are denied, whatever the effects allow.
- **The run's scratch directory** is allowed for editing, added as a working directory, and is Claude Code's
  `TMPDIR`, `TMP` and `TEMP`.
- **`delete` and `move` are troupe's own tools.** Claude Code has none for either, only its shell, and a shell rule
  matches a command's text, not the paths it touches. So when an actor declares either, the runner starts Claude Code
  with an MCP server of its own (`python -m troupe_runner_claude_code.effects_server`), whose `Delete` and `Move` are
  carried out by the plugin SDK, checked against the declaration on each call, and allowed as
  `mcp__troupe__Delete` and `mcp__troupe__Move`. With neither declared, there's no MCP server.
- **A `write` pattern holding `[`, `]`, `(`, `)`, a backslash or a leading `!`,** or a workspace or scratch path
  holding one of those or `*` or `?`, is refused with `claude-code.untranslatable-pattern`: Claude Code's rule syntax
  reads them differently, so no rule would mean what's declared.

What the rules can't cover is said, not hidden. **An allowed shell rule** (`Bash(...)`, `PowerShell(...)`) can change
any file, and **a loaded setting source**'s rules merge with the runner's, so the run sends a `log` warning naming
each. troupe's audit checks the run's changes after it ends, whatever made them. The settings file also turns off
Claude Code's automatic allowing of sandboxed shell commands. None of this is enforcement: the runner, and Claude
Code, are processes on your machine.

## What it runs

The runner finds `claude` on the `PATH` it was given, searching only absolute entries (an empty or relative entry
would resolve against the workspace), and trying each `PATHEXT` extension on Windows. No option or config names the
program. It runs Claude Code in the workspace:

```console
claude -p --output-format stream-json --verbose --no-session-persistence \
       --setting-sources "" --strict-mcp-config --max-budget-usd 5 \
       [--model M] --permission-mode dontAsk|plan --add-dir <scratch> \
       [--append-system-prompt-file <private>/character.md] --settings <private>/settings.json \
       [--mcp-config <private>/mcp.json]
```

- **The direction goes on standard input,** never on the command line, so it can't show in a process listing,
  meet Windows' command-line limit, or be re-read by `cmd.exe` when `claude` is an npm `claude.cmd`.
- **The character is appended to Claude Code's system prompt** from a file, so its own tool instructions stay.
- **`allowedTools` and `disallowedTools` go in a settings file** as `permissions.allow` and `permissions.deny`,
  with the rules translated from the actor's [effects](#effects).
- **Claude Code's automatic compaction is off,** with `autoCompactEnabled: false` in the same settings file, so a
  run never carries on from a summary of its earlier turns
  ([#279](https://github.com/troupe-run/troupe/issues/279)). It's a setting rather than `DISABLE_AUTO_COMPACT`,
  because a setting source the actor loads can replace that variable through its `env`, while the file passed with
  `--settings` ranks above every source. A run whose context fills ends with an error
  ([How a run ends](#how-a-run-ends)).
- **The private files** live in a directory of the runner's own, outside the workspace (0700 on POSIX), removed when
  the runner exits. If the temporary directory is inside the workspace, the run is refused.
- **Claude Code's environment is the runner's,** with its temporary directory pointed at the run's scratch
  directory, plus `DISABLE_AUTOUPDATER=1` and
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`. troupe gives the runner only the variables it names for it: the path,
  the home and temporary directories, the locale, proxies, `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_OAUTH_TOKEN` and
  `ANTHROPIC_API_KEY`.

### The person's settings are left out

By default the actor loads no setting sources and no MCP servers but troupe's own, when it declares `delete` or
`move`: none of the person's `~/.claude/settings.json`
hooks, permissions or default mode, and none of the workspace's `.claude/settings.json`. A run then doesn't depend on
whose machine it's on, and the actor doesn't run the hooks of the repository it works in. `settingSources` names the
sources to load instead. Logging in isn't a setting, so the person's existing login still works. `--bare` is never
used, because it never reads OAuth or the keychain. With no setting sources, the workspace's `CLAUDE.md` isn't
loaded either: the live test showed it on Claude Code 2.1.302, and reports it on every run. Add `project` to
`settingSources` for an actor that should read it.

## How a run ends

- **Each line Claude Code writes** is sent as a `run/transcript` record, unchanged (`base64` if it isn't UTF-8),
  then mapped onto run events as [the contract's table](../../contributing/runners.md#mapping-an-engine-claude-code)
  says.
- **A run whose context fills fails.** With compaction off, Claude Code ends with an error result when the API
  refuses a request as too long (`terminal_reason` `prompt_too_long`) or before sending one that wouldn't fit
  (`blocking_limit`), and the runner reports it with the reason `context-length`. A long run that got through by
  compacting before this runner turned compaction off now fails: split its task, or, once
  [#310](https://github.com/troupe-run/troupe/issues/310) lands, let its actor opt in to compaction.
- **The runner never invents a result.** When Claude Code ends without one, the runner sends none and troupe derives
  the outcome. When it ends before its init record, the runner sends an `init` of its own and a `log` error naming the
  exit code.
- **`run/cancel` and end of input** stop Claude Code before the runner exits, with no events after. On POSIX that's
  SIGTERM, then a kill after `CLAUDE_STOP_GRACE_SECONDS`. On Windows Claude Code runs in a job of its own, and the whole
  job is terminated at once, so a `claude.cmd` shim's `node` goes too. The runner never exits while Claude Code runs.
- **After the result,** `shutdown` is answered once Claude Code has exited (or has been stopped, after
  `CLAUDE_EXIT_WAIT_SECONDS`).
- **The runner's exit code** is 0 only if Claude Code exited 0. Otherwise it's Claude Code's code from 1 to 255,
  128 + n for POSIX signal n, or 1. The exact code, the path of the `claude` it ran, and Claude Code's own standard
  error all go to the runner's standard error, which troupe keeps with the run.

## Limits

Each has its default in [`defaults.py`](src/troupe_runner_claude_code/defaults.py).

| Setting | Default | What it limits |
|---|---|---|
| `DEFAULT_MAX_BUDGET_USD` | 5 | A run's spend when `maxBudgetUsd` isn't set |
| `SUMMARY_MAX_BYTES` | 4096 | One summary field of an event, before `eventMaxBytes` cuts it further |
| `CLAUDE_STOP_GRACE_SECONDS` | 5 | How long Claude Code has to exit after it's asked to stop, before it's killed |
| `CLAUDE_EXIT_WAIT_SECONDS` | 5 | How long the runner waits for Claude Code to exit after its result, before stopping it |

## Schemas

The runner publishes its schemas in its package's [`schemas/`](src/troupe_runner_claude_code/schemas/), installed
with it ([Publishing a runner's schemas](../../contributing/runners.md#publishing-a-runners-schemas)):

- [`options.schema.json`](src/troupe_runner_claude_code/schemas/options.schema.json): the options above.
- [`errors.schema.json`](src/troupe_runner_claude_code/schemas/errors.schema.json): its own error codes, each refusing
  `run/start`: `claude-code.unknown-option` and `claude-code.invalid-options` (with `details.where`),
  `claude-code.not-found` (with `details.path`, the `PATH` searched), `claude-code.start-failed`, and, with
  `details.where`, `claude-code.widens-effects` and `claude-code.untranslatable-pattern`.

## Fixtures

[`fixtures/claude-code/`](fixtures/claude-code/) holds recordings of real Claude Code runs: the native stream-json
lines as they came, scrubbed, each paired with the run events it maps to, written by hand and reviewed, with each
fixture's expected outcome and provenance. The mapping is tested against them, and the scripted runner replays them
through troupe's host.

[`tools/capture_claude.py`](tools/capture_claude.py) captures them. Every failure fixture is captured offline, against
a local stand-in for the API or an address nothing listens on, with a deliberately invalid key, so nothing reaches
Anthropic and an agent session can capture it. Only `success-with-tools` needs a real credential, and the owner
captures it.

`context-limit-refused` and `context-limit-blocked` are captured through the runner's own launch, so compaction is
off, against a stand-in that reports a context near the window. The tool refuses to write either one when Claude Code
reported compacting, sent more requests than compaction being off allows, or ended for another reason. A recapture on
a newer Claude Code therefore checks again that the runner's setting still turns compaction off.

## Tests

The tests import nothing from troupe. They drive the runner over pipes with a stand-in `claude`
([`tests/fake_claude.py`](tests/fake_claude.py)) first on its `PATH`, and validate every message against the schemas
in `protocol/`, with this runner's own schemas filling the contract's extension points. troupe's own tests run it
through the host, the conformance suite and `troupe perform`, and an opt-in live test runs it against real Claude Code
(`TROUPE_LIVE_CLAUDE_CODE=1`).
