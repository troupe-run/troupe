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

## What it runs

The runner finds `claude` on the `PATH` it was given, searching only absolute entries (an empty or relative entry
would resolve against the workspace), and trying each `PATHEXT` extension on Windows. No option or config names the
program. It runs Claude Code in the workspace:

```console
claude -p --output-format stream-json --verbose --no-session-persistence \
       --setting-sources "" --strict-mcp-config --max-budget-usd 5 \
       [--model M] [--permission-mode P] \
       [--append-system-prompt-file <private>/character.md] [--settings <private>/settings.json]
```

- **The direction goes on standard input,** never on the command line, so it can't show in a process listing,
  meet Windows' command-line limit, or be re-read by `cmd.exe` when `claude` is an npm `claude.cmd`.
- **The character is appended to Claude Code's system prompt** from a file, so its own tool instructions stay.
- **`allowedTools` and `disallowedTools` go in a settings file** as `permissions.allow` and `permissions.deny`.
- **The private files** live in a directory of the runner's own, outside the workspace (0700 on POSIX), removed when
  the runner exits. If the temporary directory is inside the workspace, the run is refused.
- **Claude Code's environment is the runner's,** plus `DISABLE_AUTOUPDATER=1` and
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`. troupe gives the runner only the variables it names for it: the path,
  the home and temporary directories, the locale, proxies, `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_OAUTH_TOKEN` and
  `ANTHROPIC_API_KEY`.

### The person's settings are left out

By default the actor loads no setting sources and no MCP servers: none of the person's `~/.claude/settings.json`
hooks, permissions or default mode, and none of the workspace's `.claude/settings.json`. A run then doesn't depend on
whose machine it's on, and the actor doesn't run the hooks of the repository it works in. `settingSources` names the
sources to load instead. Logging in isn't a setting, so the person's existing login still works. `--bare` is never
used, because it never reads OAuth or the keychain. Whether `CLAUDE.md` files load with no setting sources isn't
documented; the live test reports it.

## How a run ends

- **Each line Claude Code writes** is sent as a `run/transcript` record, unchanged (`base64` if it isn't UTF-8),
  then mapped onto run events as [the contract's table](../../contributing/runners.md#mapping-an-engine-claude-code)
  says.
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
  `claude-code.not-found` (with `details.path`, the `PATH` searched) and `claude-code.start-failed`.

## Fixtures

[`fixtures/claude-code/`](fixtures/claude-code/) holds recordings of real Claude Code runs: the native stream-json
lines as they came, scrubbed, each paired with the run events it maps to, written by hand and reviewed, with each
fixture's expected outcome and provenance. The mapping is tested against them, and the scripted runner replays them
through troupe's host.

[`tools/capture_claude.py`](tools/capture_claude.py) captures them. Every failure fixture is captured offline, against
a local stand-in for the API or an address nothing listens on, with a deliberately invalid key, so nothing reaches
Anthropic and an agent session can capture it. Only `success-with-tools` needs a real credential, and the owner
captures it.

## Tests

The tests import nothing from troupe. They drive the runner over pipes with a stand-in `claude`
([`tests/fake_claude.py`](tests/fake_claude.py)) first on its `PATH`, and validate every message against the schemas
in `protocol/`, with this runner's own schemas filling the contract's extension points. troupe's own tests run it
through the host, the conformance suite and `troupe perform`, and an opt-in live test runs it against real Claude Code
(`TROUPE_LIVE_CLAUDE_CODE=1`).
