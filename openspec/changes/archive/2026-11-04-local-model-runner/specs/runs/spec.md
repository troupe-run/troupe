# Spec Delta

## MODIFIED Requirements

### Requirement: Perform knows the runners troupe ships by name
`perform` SHALL turn an actor's runner name into a command line only through troupe's table of runners it ships,
which SHALL name `scripted`, `claude-code` and `ollama`. Any other name SHALL be refused with `runner.unknown`, naming
the runners troupe knows, before anything is recorded.

#### Scenario: The Claude Code runner
- **WHEN** a person performs an actor whose runner is `claude-code`
- **THEN** `perform` starts the Claude Code runner

#### Scenario: The Ollama runner
- **WHEN** a person performs an actor whose runner is `ollama`
- **THEN** `perform` starts the Ollama runner

#### Scenario: A runner troupe doesn't ship
- **WHEN** a person performs an actor whose runner is `codex`
- **THEN** it is refused with `runner.unknown`, naming `claude-code`, `ollama` and `scripted`, and nothing is recorded

### Requirement: Perform passes a runner only the variables it is known to need
`perform` SHALL start a runner with the environment variables troupe's runner table names for it, each taken from
`perform`'s own environment when set there, and SHALL pass no others. The scripted runner and the Ollama runner SHALL
be named none. The Claude Code runner SHALL be named what Claude Code needs to run and find the person's login.

#### Scenario: The Claude Code runner gets its login's variables
- **WHEN** `perform` runs with `PATH`, `HOME` and `CLAUDE_CODE_OAUTH_TOKEN` set, and performs a `claude-code` actor
- **THEN** the runner's environment holds those three with the same values

#### Scenario: Nothing else reaches it
- **WHEN** `perform` runs with `AWS_SECRET_ACCESS_KEY` set, and performs a `claude-code` actor
- **THEN** the runner's environment has no `AWS_SECRET_ACCESS_KEY`

#### Scenario: A name that isn't set
- **WHEN** `ANTHROPIC_API_KEY` isn't set in `perform`'s environment
- **THEN** the runner's environment has no `ANTHROPIC_API_KEY`, rather than an empty one

#### Scenario: The scripted runner gets nothing new
- **WHEN** `perform` runs with `PATH` set, and performs a `scripted` actor
- **THEN** the runner's environment has only the platform minimum

#### Scenario: The Ollama runner gets nothing new
- **WHEN** `perform` runs with `PATH`, `OLLAMA_HOST` and `HTTPS_PROXY` set, and performs an `ollama` actor
- **THEN** the runner's environment has only the platform minimum
