# Spec Delta

## MODIFIED Requirements

### Requirement: Every run has a budget
The runner SHALL always pass Claude Code a budget: `maxBudgetUsd` when the options set it, and otherwise a default of
USD 5, a named setting in one place in the runner. The runner SHALL always pass a permission mode that denies every
tool call no rule allows: `plan` when the options set it, and otherwise `dontAsk`, so the runner never grants more
than config asks for.

#### Scenario: No budget in the options
- **WHEN** a run starts without `maxBudgetUsd`
- **THEN** Claude Code is given `--max-budget-usd 5`

#### Scenario: A budget in the options
- **WHEN** a run starts with `maxBudgetUsd` 0.1
- **THEN** Claude Code is given `--max-budget-usd 0.1`

#### Scenario: No permission mode in the options
- **WHEN** a run starts without `permissionMode`
- **THEN** Claude Code is given `--permission-mode dontAsk`

### Requirement: Options reach Claude Code without free text on its command line
`model`, `maxBudgetUsd` and the permission mode SHALL be passed as Claude Code's flags of those names. `allowedTools`
and `disallowedTools`, and the rules translated from the effects, SHALL be passed as permission rules in a settings
file outside the workspace, so no value from config is parsed by a shell on any platform.

#### Scenario: Tool rules with spaces and parentheses
- **WHEN** `allowedTools` is `["Bash(git status)", "Read"]`
- **THEN** Claude Code is given `--settings` naming a file whose `permissions.allow` holds those two rules, and no
  argument of its command line contains them

## ADDED Requirements

### Requirement: Write effects become edit rules
The runner SHALL translate each `write` pattern into an allow rule for Claude Code's file-editing tools, `Edit(//…)`,
rooted at the workspace's absolute path in Claude Code's form (`//c/…` for a Windows drive). It SHALL deny editing
under the workspace's `.git` and `.troupe`. Its `init` event SHALL report `effects` as `translated`.

#### Scenario: A write pattern
- **WHEN** the workspace is `/w/t` and `effects.write` is `["out/**"]`
- **THEN** the settings file's `permissions.allow` holds `Edit(//w/t/out/**)`, and `permissions.deny` holds
  `Edit(//w/t/.git/**)` and `Edit(//w/t/.troupe/**)`

#### Scenario: A read-only actor
- **WHEN** the actor declares no effects
- **THEN** the settings file allows no `Edit` rule other than the scratch directory's

#### Scenario: A write pattern on Windows
- **WHEN** the workspace is `C:\w\t` and `effects.write` is `["src/*.py"]`
- **THEN** `permissions.allow` holds `Edit(//c/w/t/src/*.py)`

### Requirement: The scratch directory is Claude Code's to use
The runner SHALL let Claude Code read and edit anything in the run's scratch directory, add it as a working
directory, and point Claude Code's temporary-directory variables at it. The runner's own private files SHALL stay
outside the scratch directory, where Claude Code can't edit them.

#### Scenario: Scratch in the settings file
- **WHEN** a run starts with scratch `/s/run`
- **THEN** Claude Code is given `--add-dir /s/run`, its `permissions.allow` holds `Edit(//s/run/**)`, and `TMPDIR` in
  its environment is `/s/run`
- **AND** the settings file isn't under `/s/run`

### Requirement: Delete and move effects are troupe's own tools
When the actor declares `delete` or `move`, the runner SHALL offer Claude Code troupe's `Delete` and `Move` tools,
carried out by the SDK and checked against the declaration on each call, through an MCP server of its own named only
by `--mcp-config`, and allow them by rule. Their calls and results SHALL be reported as the runner reports other tool
calls. With neither declared, the runner SHALL offer no MCP server.

#### Scenario: A declared delete
- **WHEN** the actor declares `delete` for `drafts/**` and Claude Code calls troupe's `Delete` on `drafts/a.md`
- **THEN** the file is removed, and a `tool_call` and `tool_result` for it are reported

#### Scenario: A refused move
- **WHEN** the actor declares `move` for `drafts/**` and Claude Code calls troupe's `Move` from `drafts/a.md` to
  `docs/a.md`
- **THEN** the result Claude Code gets is an error naming the `move` effect, and nothing moves

#### Scenario: Nothing to delete or move
- **WHEN** the actor declares only `write`
- **THEN** Claude Code is given no `--mcp-config`

### Requirement: Options can't widen the effects
`run/start` SHALL be refused with `claude-code.widens-effects`, naming the option and the effect to declare
instead, when `permissionMode` is `acceptEdits`, `auto`, `bypassPermissions` or `manual`, or when `allowedTools`
holds a rule for `Edit`, `Write`, `NotebookEdit`, `MultiEdit` or troupe's own tools. `disallowedTools` MAY name any
tool, since a deny only narrows.

#### Scenario: An actor that accepts edits
- **WHEN** the options set `permissionMode` to `acceptEdits`
- **THEN** `run/start` is refused with `claude-code.widens-effects`, whose fix says to declare `effects.write` and
  unset `permissionMode`

#### Scenario: An allowed edit rule
- **WHEN** `allowedTools` holds `Edit(src/**)`
- **THEN** `run/start` is refused with `claude-code.widens-effects`, naming `allowedTools` and `Edit(src/**)`

#### Scenario: A denied edit rule
- **WHEN** `disallowedTools` holds `Edit(docs/**)`
- **THEN** the run starts, with `Edit(docs/**)` in `permissions.deny`

### Requirement: What the translation can't cover is said, not hidden
Before the result, the runner SHALL send a `log` warning naming what can change files outside the translated rules:
each allowed `Bash` or `PowerShell` rule, and any loaded setting source, whose rules Claude Code merges with the
runner's. It SHALL turn off Claude Code's automatic allowing of sandboxed shell commands.

#### Scenario: An allowed shell command
- **WHEN** `allowedTools` holds `Bash(uv run pytest *)`
- **THEN** the run's events include a `log` warning that `Bash(uv run pytest *)` can change files the effects don't
  declare, and that troupe's audit checks them after the run

#### Scenario: Project settings loaded
- **WHEN** `settingSources` holds `project`
- **THEN** the run's events include a `log` warning that the project's settings may allow more than the effects
  declare

### Requirement: A pattern Claude Code would read differently is refused
`run/start` SHALL be refused with `claude-code.untranslatable-pattern`, naming the pattern or path and the character,
when a `write` pattern holds `[`, `]`, `(`, `)`, a backslash or a leading `!`, or the workspace's or scratch
directory's path holds one of those or `*` or `?`: characters Claude Code's rule syntax reads differently, or as
the rule's end. `delete` and `move` patterns SHALL be kept whatever they hold, since troupe's own tools read them.

#### Scenario: A bracket in a pattern
- **WHEN** `effects.write` holds `app/[id]/page.tsx`
- **THEN** `run/start` is refused with `claude-code.untranslatable-pattern`, naming the pattern and `[`
