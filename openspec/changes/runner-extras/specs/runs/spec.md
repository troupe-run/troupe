## MODIFIED Requirements

### Requirement: Perform knows the runners troupe ships by name
`perform` SHALL turn an actor's runner name into a command line only through troupe's table of runners it ships,
which SHALL name `scripted`, `claude-code`, `ollama` and `openai`, and say for each whether it takes a runtime:
`required`, `optional` or `none`, and whether it is installed through the `troupe-run` extra named after it rather
than the base install. Any other name SHALL be refused with `runner.unknown`, naming the runners troupe knows, before
anything is recorded.

#### Scenario: The Claude Code runner
- **WHEN** a person performs an actor whose runner is `claude-code`
- **THEN** `perform` starts the Claude Code runner

#### Scenario: The Ollama runner
- **WHEN** a person performs an actor whose runner is `ollama`
- **THEN** `perform` starts the Ollama runner

#### Scenario: The OpenAI runner
- **WHEN** a person performs an actor whose runner is `openai`
- **THEN** `perform` starts the OpenAI runner

#### Scenario: A runner troupe doesn't ship
- **WHEN** a person performs an actor whose runner is `codex`
- **THEN** it is refused with `runner.unknown`, naming `claude-code`, `ollama`, `openai` and `scripted`, and
  nothing is recorded

#### Scenario: What each runner takes
- **WHEN** troupe's runner table is read
- **THEN** `claude-code` and `ollama` take no runtime, `scripted` takes one optionally, and `openai` requires
  one

#### Scenario: Which extra each runner needs
- **WHEN** troupe's runner table is read while every runner plugin depends only on the SDK
- **THEN** no runner is in an extra

#### Scenario: The table and the bundle agree
- **WHEN** troupe's runner table says a runner is in the base install while `troupe-run` has it in an extra, or the
  reverse
- **THEN** `scripts/check.py` fails, naming the runner, the table and `packages/troupe-run/pyproject.toml`

## ADDED Requirements

### Requirement: Perform refuses an actor whose runner isn't installed
When an actor's runner is in troupe's table but its package isn't installed, `perform` SHALL refuse with
`runner.not-installed` before anything is recorded, naming the runner, its package and its extra. The fix SHALL say to
install `troupe-run[<extra>]` with the command on the install page, or, for a runner with no extra, to reinstall troupe
or run `uv sync` in a checkout of troupe.

#### Scenario: A library-backed runner that isn't installed
- **WHEN** a person performs an actor whose runner, `lm-studio`, is in an extra, and its package isn't installed
- **THEN** it is refused with `runner.not-installed`, with details naming the runner, the package and `lm-studio`,
  and a fix naming `troupe-run[lm-studio]` and the install page
- **AND** nothing is recorded, and no run directory or worktree is made

#### Scenario: A base runner missing from a broken install
- **WHEN** a person performs an actor whose runner is `scripted`, and `troupe_runner_scripted` isn't installed
- **THEN** it is refused with `runner.not-installed`, with no extra in its details, and a fix naming the install page and
  `uv sync`

#### Scenario: Rehearsing
- **WHEN** a person runs `troupe perform <actor> --rehearse` for an actor whose runner isn't installed
- **THEN** it is refused with `runner.not-installed`, as a perform would be
