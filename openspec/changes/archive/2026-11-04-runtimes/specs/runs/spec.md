# Spec Delta

## ADDED Requirements

### Requirement: A run's start records its runtime and where each value came from
When an actor names a runtime, the run's start SHALL record the runtime's name, its endpoint and model, each with its
source, and, when it has a credential, the variable's name and its source. It SHALL NOT record the credential's value.

#### Scenario: A run on a theatre-chosen endpoint
- **WHEN** config sets `runtimes.openai.endpoint=https://gateway.example/v1` and an actor on `openai` is performed
- **THEN** the run's start records the endpoint `https://gateway.example/v1` with source `theatre`, and the variable
  `OPENAI_API_KEY` with source `default`

#### Scenario: A run with no runtime
- **WHEN** an actor that names no runtime is performed
- **THEN** the run's start has no `runtime` field

### Requirement: troupe masks the credential in everything it keeps from a run
troupe SHALL replace the run's credential value with `[credential]` in every run event, transcript record and byte of
kept standard error it stores, and in any error or notice, before it is written or sent, including where the value
is split across reads.

#### Scenario: An echoed key in a log event
- **WHEN** a runner sends a `log` event whose message holds the credential
- **THEN** the recorded event's message holds `[credential]` in its place

#### Scenario: A key split across two reads of standard error
- **WHEN** a runner writes the credential to standard error in two writes, split in the middle
- **THEN** the kept standard error holds `[credential]`, and no part of the value that the split left on either side

#### Scenario: The JSON-escaped form
- **WHEN** a credential holds `/` and a runner sends it inside JSON text as `\/`
- **THEN** that form is masked too

### Requirement: A rehearsal shows the run's runtime
A rehearsed `perform` SHALL show the runtime the run would use, with each value's source and whether its credential's
variable is set, and SHALL refuse what perform would refuse about the runtime.

#### Scenario: A rehearsal on openai
- **WHEN** a person rehearses an actor on `openai` and `OPENAI_API_KEY` is set
- **THEN** the rehearsal shows the endpoint, the model and the variable `OPENAI_API_KEY`, set, each with its source,
  and no part of the key

## MODIFIED Requirements

### Requirement: A run uses the actor as config defines it
`perform` SHALL take the actor's runner, options, effects, effect check, character, runtime and model from the merged
config, as it is when the run starts, and resolve the runtime as spec: runtimes says. A request SHALL name only the
actor, the direction and whether to rehearse.

#### Scenario: The character reaches the runner
- **WHEN** config gives `tester` a character, and a person performs `tester` with the scripted runner and a script
  that checks the character it receives
- **THEN** the run succeeds, because the runner received exactly that character

#### Scenario: Config changed between two runs
- **WHEN** a person performs `tester`, changes its runner's options, and performs it again
- **THEN** the second run uses the new options

#### Scenario: The effects reach the runner
- **WHEN** config gives `tester` `effects.write: ["out/**"]` and a person performs it
- **THEN** the runner's `run/start` carries `write: ["out/**"]` and empty `delete` and `move`

#### Scenario: The runtime reaches the runner
- **WHEN** config gives `tester` the runtime `ollama` and the model `llama3.2`, and a person performs it with a script
  that checks the runtime it receives
- **THEN** the run succeeds, because the runner received the endpoint `http://127.0.0.1:11434` and the model
  `llama3.2`

### Requirement: Perform passes a runner only the variables it is known to need
`perform` SHALL start a runner with the environment variables troupe's runner table names for it, each taken from
`perform`'s own environment when set there, and, when the run's runtime has a credential, `TROUPE_RUNTIME_CREDENTIAL`
holding its value, and SHALL pass no others. The scripted runner SHALL be named none. The Claude Code runner SHALL be
named what Claude Code needs to run and find the person's login.

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

#### Scenario: The credential under troupe's name only
- **WHEN** `MY_KEY` holds a key, a runtime's credential names `MY_KEY`, and a `scripted` actor on it is performed
- **THEN** the runner's environment holds the key as `TROUPE_RUNTIME_CREDENTIAL`, and has no `MY_KEY`

### Requirement: Perform knows the runners troupe ships by name
`perform` SHALL turn an actor's runner name into a command line only through troupe's table of runners it ships,
which SHALL name `scripted` and `claude-code`, and say for each whether it takes a runtime: `required`, `optional`
or `none`. Any other name SHALL be refused with `runner.unknown`, naming the runners troupe knows, before anything is
recorded.

#### Scenario: The Claude Code runner
- **WHEN** a person performs an actor whose runner is `claude-code`
- **THEN** `perform` starts the Claude Code runner

#### Scenario: A runner troupe doesn't ship
- **WHEN** a person performs an actor whose runner is `codex`
- **THEN** it is refused with `runner.unknown`, naming `claude-code` and `scripted`, and nothing is recorded

#### Scenario: What each runner takes
- **WHEN** troupe's runner table is read
- **THEN** `claude-code` takes no runtime and `scripted` takes one optionally
