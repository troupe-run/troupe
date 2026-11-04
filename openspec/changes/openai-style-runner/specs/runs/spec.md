## MODIFIED Requirements

### Requirement: Perform knows the runners troupe ships by name
`perform` SHALL turn an actor's runner name into a command line only through troupe's table of runners it ships,
which SHALL name `scripted`, `claude-code`, `ollama` and `openai-chat`, and say for each whether it takes a runtime:
`required`, `optional` or `none`. Any other name SHALL be refused with `runner.unknown`, naming the runners troupe
knows, before anything is recorded.

#### Scenario: The Claude Code runner
- **WHEN** a person performs an actor whose runner is `claude-code`
- **THEN** `perform` starts the Claude Code runner

#### Scenario: The Ollama runner
- **WHEN** a person performs an actor whose runner is `ollama`
- **THEN** `perform` starts the Ollama runner

#### Scenario: The OpenAI-style runner
- **WHEN** a person performs an actor whose runner is `openai-chat`
- **THEN** `perform` starts the OpenAI-style runner

#### Scenario: A runner troupe doesn't ship
- **WHEN** a person performs an actor whose runner is `codex`
- **THEN** it is refused with `runner.unknown`, naming `claude-code`, `ollama`, `openai-chat` and `scripted`, and
  nothing is recorded

#### Scenario: What each runner takes
- **WHEN** troupe's runner table is read
- **THEN** `claude-code` and `ollama` take no runtime, `scripted` takes one optionally, and `openai-chat` requires
  one

### Requirement: Perform passes a runner only the variables it is known to need
`perform` SHALL start a runner with the environment variables troupe's runner table names for it, each taken from
`perform`'s own environment when set there, and, when the run's runtime has a credential, `TROUPE_RUNTIME_CREDENTIAL`
holding its value, and SHALL pass no others. The scripted runner and the Ollama runner SHALL be named none. The
Claude Code runner SHALL be named what Claude Code needs to run and find the person's login. The OpenAI-style runner
SHALL be named only what it needs to reach a service through a proxy and trust its certificate.

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

#### Scenario: The credential under troupe's name only
- **WHEN** `MY_KEY` holds a key, a runtime's credential names `MY_KEY`, and a `scripted` actor on it is performed
- **THEN** the runner's environment holds the key as `TROUPE_RUNTIME_CREDENTIAL`, and has no `MY_KEY`

#### Scenario: The OpenAI-style runner gets its proxy, its certificates and its credential
- **WHEN** `perform` runs with `HTTPS_PROXY`, `SSL_CERT_FILE` and `OPENAI_API_KEY` set, and performs an `openai-chat`
  actor on the runtime `openai`
- **THEN** the runner's environment holds `HTTPS_PROXY` and `SSL_CERT_FILE` with the same values, and the key as
  `TROUPE_RUNTIME_CREDENTIAL`, and has no `OPENAI_API_KEY`
