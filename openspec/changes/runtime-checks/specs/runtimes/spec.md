# runtimes: delta

## ADDED Requirements

### Requirement: An actor's runtime fits its runner
Config SHALL refuse an actor whose runtime doesn't fit its runner, judged from the runtime's built-in and theatre
values: a runtime with a credential, for a runner that sends none, or an endpoint whose path the runner can't use.
The error SHALL name the actor's `runtime` path, the runner, the runtime, why it doesn't fit, and the runtimes that
fit. A change to a runtime that makes an actor on it unfit SHALL be refused the same way.

#### Scenario: An Ollama actor on a runtime with a credential
- **WHEN** a person sets `actors.tester.runner=ollama` and `actors.tester.runtime=openai`
- **THEN** it is refused, naming `actors.tester.runtime`, the `ollama` runner and the runtime `openai`, saying the
  runner sends no credential and `openai` has one, and listing `ollama` as a runtime that fits

#### Scenario: An Ollama actor on an endpoint with a path
- **WHEN** a person sets `actors.tester.runner=ollama` and `actors.tester.runtime=lm-studio`
- **THEN** it is refused, saying the `ollama` runner needs an endpoint with no path and `lm-studio`'s has one

#### Scenario: An OpenAI actor on an endpoint with no path
- **WHEN** a person sets `actors.tester.runner=openai` and `actors.tester.runtime=ollama`
- **THEN** it is refused, saying the `openai` runner needs an endpoint with a path, such as `/v1`, and listing
  `lm-studio` and `openai` as runtimes that fit

#### Scenario: A runtime defined in config
- **WHEN** config defines `runtimes.gpu-box.endpoint=http://10.0.0.5:11434` and a person sets an `ollama` actor's
  runtime to `gpu-box`
- **THEN** it is accepted

#### Scenario: A change to the runtime makes its actor unfit
- **WHEN** an `ollama` actor names the runtime `ollama`, and a person sets `runtimes.ollama.credential.env=MY_KEY`
- **THEN** it is refused, naming the actor's `runtime` path, and config is unchanged

#### Scenario: Every runtime fits a runner that takes any
- **WHEN** a `scripted` actor names any runtime there is
- **THEN** no fit is refused

### Requirement: Perform refuses a runtime that doesn't fit its runner
Perform SHALL judge the run's runtime as resolved, the person's environment included, by the same rule as config, and
SHALL refuse a runtime that doesn't fit with `runtime.unfit`, naming the actor, the runner, the runtime and why, before
anything is recorded, before its credential is read, and before any runner is started.

#### Scenario: An endpoint variable gives an Ollama actor a path
- **WHEN** an `ollama` actor names the runtime `ollama`, `TROUPE_RUNTIME_OLLAMA_ENDPOINT` is
  `http://127.0.0.1:11434/v1`, and the actor is performed
- **THEN** perform fails with `runtime.unfit`, naming `TROUPE_RUNTIME_OLLAMA_ENDPOINT` as where the endpoint came
  from, no runner is started, and nothing is recorded

#### Scenario: A credential variable on an Ollama actor's runtime
- **WHEN** an `ollama` actor names the runtime `ollama`, and `TROUPE_RUNTIME_OLLAMA_CREDENTIAL_ENV` is set
- **THEN** perform fails with `runtime.unfit`, whether or not the variable it names is set, and nothing is recorded

#### Scenario: A rehearsal
- **WHEN** the same actor is rehearsed
- **THEN** the rehearsal fails with `runtime.unfit`

### Requirement: An endpoint refused for its user info is repeated nowhere
When troupe refuses an endpoint that holds user info, no error, notice, client message, event, transcript, log or
standard error SHALL hold the user info or any part of the endpoint's value, wherever the refusal happens: config, a
runtime variable, or a runner's refusal of `run/start`.

#### Scenario: A runtime variable holding a password
- **WHEN** `TROUPE_RUNTIME_OLLAMA_ENDPOINT` is `https://user:<canary>@example.com/v1` and a person runs a command that
  resolves the runtime
- **THEN** it fails with `runtime.invalid-value`, naming the variable, and neither the standard error nor the client
  message holds the canary

#### Scenario: Config set with a password
- **WHEN** a person runs `troupe config set runtimes.box.endpoint=https://user:<canary>@example.com/v1`
- **THEN** it is refused with `config.invalid`, and neither the standard error nor the client message holds the canary

#### Scenario: A run start holding a password
- **WHEN** a runner built on the plugin SDK is sent a `run/start` whose `runtime.endpoint` is
  `https://user:<canary>@example.com/v1`
- **THEN** it refuses with `runner.invalid-params` naming `runtime.endpoint`, and neither the error nor the runner's
  standard error holds the canary

## MODIFIED Requirements

### Requirement: An actor names its runtime and may set its model
An actor MAY name a `runtime`, which SHALL be a built-in runtime or one in config, and MAY set a `model`. An actor
SHALL name a runtime when its runner requires one, SHALL NOT name one when its runner takes none, and SHALL NOT set a
`model` without a runtime.

#### Scenario: A runtime that doesn't exist
- **WHEN** a person sets `actors.tester.runtime=nowhere`
- **THEN** it is refused, naming the path and the runtimes that exist and fit the actor's runner

#### Scenario: A runner that takes no runtime
- **WHEN** an actor whose runner is `claude-code` names the runtime `openai`
- **THEN** it is refused, naming the path and saying the `claude-code` runner takes no runtime

#### Scenario: A model without a runtime
- **WHEN** a person sets `actors.tester.model=gpt-test` and `tester` names no runtime
- **THEN** it is refused, naming `actors.tester.runtime`

#### Scenario: An Ollama actor without a runtime
- **WHEN** a person sets `actors.tester.runner=ollama` and `tester` names no runtime
- **THEN** it is refused, naming `actors.tester.runtime` and saying the `ollama` runner needs one, listing only the
  runtimes that fit it: `ollama`, and not `lm-studio` or `openai`

#### Scenario: No runtime fits
- **WHEN** an `ollama` actor names no runtime, and config overrides the built-in `ollama` with a credential
- **THEN** it is refused, saying no runtime there is fits the `ollama` runner, and how to define one

### Requirement: A credential holding a character a request header can't carry is refused
A run's credential whose value holds any character other than visible ASCII (`!` to `~`), such as whitespace, a
control character or a non-ASCII letter, SHALL refuse the run with `runtime.credential-malformed`, naming the runtime
and the variable (as "A refusal never repeats a credential variable's name taken from the environment" says) but not
the value, before anything is recorded and before any runner is started.

#### Scenario: A key read with its line ending
- **WHEN** `OPENAI_API_KEY` holds `sk-test-q7ZxW9pL4vR2\r\n` and an actor on `openai` is performed
- **THEN** perform fails with `runtime.credential-malformed`, naming `openai` and `OPENAI_API_KEY`, the error holds no
  part of the value, no runner is started, and nothing is recorded

#### Scenario: A space inside the key
- **WHEN** a runtime's credential variable holds `sk-test q7ZxW9pL4vR2`
- **THEN** the run is refused with `runtime.credential-malformed`

#### Scenario: A character outside ASCII
- **WHEN** a runtime's credential variable holds `sk-test-€abcdefgh`
- **THEN** the run is refused with `runtime.credential-malformed`, the error holds no part of the value, and nothing
  is recorded

#### Scenario: A well-formed key
- **WHEN** a runtime's credential variable holds `sk-test-q7ZxW9pL4vR2` and its endpoint is `https`
- **THEN** the run starts with that credential

### Requirement: Config get shows a runtime's resolved values and their sources
`troupe config get --resolved` SHALL show every runtime, built-in or in config, and `--resolved runtimes.<name>` one
runtime: each field's value and source (`default`, `theatre` or `env`), and for a credential its variable's name, or
for a name from the environment the variable that named it, and whether that variable is set, never its value.
`--resolved` with any other path SHALL be refused, naming the path.

#### Scenario: The built-in openai runtime
- **WHEN** config has no runtimes, `OPENAI_API_KEY` is set, and a person runs `troupe config get --resolved
  runtimes.openai`
- **THEN** it shows the endpoint from `default`, no model, and the credential variable `OPENAI_API_KEY` from
  `default`, set

#### Scenario: A credential variable's name from the environment
- **WHEN** `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV` is `a3f9c2e17b4d8e05f6a1` and a person runs `troupe config get
  --resolved runtimes.openai`
- **THEN** it shows the credential as named by `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV`, from `env`, not set, and
  neither its output nor its client message holds any part of `a3f9c2e17b4d8e05f6a1`

#### Scenario: The price of the runtime's model
- **WHEN** config sets `runtimes.openai.model=gpt-test` and a price for `gpt-test`, and a person runs `troupe config
  get --resolved runtimes.openai`
- **THEN** it shows that price with source `theatre`

#### Scenario: Another path
- **WHEN** a person runs `troupe config get --resolved actors.tester`
- **THEN** it is refused, naming the path and saying only runtimes have resolved values

## RENAMED Requirements

- FROM: `### Requirement: A credential holding whitespace or a control character is refused`
- TO: `### Requirement: A credential holding a character a request header can't carry is refused`
