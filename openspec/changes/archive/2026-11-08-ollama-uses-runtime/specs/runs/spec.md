## MODIFIED Requirements

### Requirement: Perform knows the runners troupe ships by name
`perform` SHALL turn an actor's runner name into a command line only through troupe's table of runners it ships,
which SHALL name `scripted`, `claude-code`, `ollama` and `openai`, and say for each whether it takes a runtime:
`required`, `optional` or `none`. Any other name SHALL be refused with `runner.unknown`, naming the runners troupe
knows, before anything is recorded.

#### Scenario: The Claude Code runner
- **WHEN** a person performs an actor whose runner is `claude-code`
- **THEN** `perform` starts the Claude Code runner

#### Scenario: The Ollama runner
- **WHEN** a person performs an actor whose runner is `ollama` and whose runtime is `ollama`
- **THEN** `perform` starts the Ollama runner, its `run/start` carries the runtime `ollama` with the actor's model,
  and the run's start records that runtime

#### Scenario: The OpenAI runner
- **WHEN** a person performs an actor whose runner is `openai`
- **THEN** `perform` starts the OpenAI runner

#### Scenario: A runner troupe doesn't ship
- **WHEN** a person performs an actor whose runner is `codex`
- **THEN** it is refused with `runner.unknown`, naming `claude-code`, `ollama`, `openai` and `scripted`, and
  nothing is recorded

#### Scenario: What each runner takes
- **WHEN** troupe's runner table is read
- **THEN** `claude-code` takes no runtime, `scripted` takes one optionally, and `ollama` and `openai` require one
