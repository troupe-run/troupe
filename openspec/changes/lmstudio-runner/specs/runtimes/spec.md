# Spec Delta

## MODIFIED Requirements

### Requirement: troupe has built-in runtimes
troupe SHALL define the runtimes `openai` (endpoint `https://api.openai.com/v1`, credential from `OPENAI_API_KEY`),
`ollama` (endpoint `http://127.0.0.1:11434`, no credential) and `lm-studio` (endpoint `http://127.0.0.1:1234`, no
credential), as defaults in one named place. No built-in runtime SHALL name a model or a price.

#### Scenario: A built-in needs no config
- **WHEN** config has no `runtimes` and an actor names the runtime `ollama`
- **THEN** the actor is valid, and the runtime's endpoint is `http://127.0.0.1:11434` with source `default`

#### Scenario: No built-in price
- **WHEN** config has no `runtimes` and an actor on `openai` with the model `gpt-test` is performed
- **THEN** the run has no price, and its `run/start` carries none

#### Scenario: LM Studio's built-in is its server root
- **WHEN** config has no `runtimes` and a person runs `troupe config get --resolved runtimes.lm-studio`
- **THEN** it shows the endpoint `http://127.0.0.1:1234` from `default`, the base LM Studio's own API lives under

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
  runtimes that fit it: `lm-studio` and `ollama`, and not `openai`

#### Scenario: No runtime fits
- **WHEN** an `ollama` actor names no runtime, and config overrides the built-ins `ollama` and `lm-studio` with a
  credential
- **THEN** it is refused, saying no runtime there is fits the `ollama` runner, and how to define one

### Requirement: An actor's runtime fits its runner
Config SHALL refuse an actor whose runtime doesn't fit its runner, judged from the runtime's built-in and theatre
values: a runtime with a credential, for a runner that sends none, an endpoint whose path the runner can't use, or an
`https` endpoint, for a runner that can only reach plain `http`.
The error SHALL name the actor's `runtime` path, the runner, the runtime, why it doesn't fit, and the runtimes that
fit. A change to a runtime that makes an actor on it unfit SHALL be refused the same way.

#### Scenario: An Ollama actor on a runtime with a credential
- **WHEN** a person sets `actors.tester.runner=ollama` and `actors.tester.runtime=openai`
- **THEN** it is refused, naming `actors.tester.runtime`, the `ollama` runner and the runtime `openai`, saying the
  runner sends no credential and `openai` has one, and listing `lm-studio` and `ollama` as runtimes that fit

#### Scenario: An Ollama actor on an endpoint with a path
- **WHEN** config defines `runtimes.lm-studio-openai.endpoint=http://127.0.0.1:1234/v1`, and a person sets
  `actors.tester.runner=ollama` and `actors.tester.runtime=lm-studio-openai`
- **THEN** it is refused, saying the `ollama` runner needs an endpoint with no path and `lm-studio-openai`'s has one

#### Scenario: An OpenAI actor on an endpoint with no path
- **WHEN** a person sets `actors.tester.runner=openai` and `actors.tester.runtime=ollama`
- **THEN** it is refused, saying the `openai` runner needs an endpoint with a path, such as `/v1`, and listing
  `openai` as a runtime that fits

#### Scenario: A runtime defined in config
- **WHEN** config defines `runtimes.gpu-box.endpoint=http://10.0.0.5:11434` and a person sets an `ollama` actor's
  runtime to `gpu-box`
- **THEN** it is accepted

#### Scenario: A change to the runtime makes its actor unfit
- **WHEN** an `ollama` actor names the runtime `ollama`, and a person sets `runtimes.ollama.credential.env=MY_KEY`
- **THEN** it is refused, naming the actor's `runtime` path, and config is unchanged

#### Scenario: An LM Studio actor on an https endpoint
- **WHEN** config defines `runtimes.remote-lm.endpoint=https://lm.example.com`, and a person sets
  `actors.tester.runner=lm-studio` and `actors.tester.runtime=remote-lm`
- **THEN** it is refused, saying the `lm-studio` runner can only reach a plain `http` endpoint and `remote-lm` has an
  `https` one, and listing `lm-studio` and `ollama` as runtimes that fit

#### Scenario: Every runtime fits a runner that takes any
- **WHEN** a `scripted` actor names any runtime there is
- **THEN** no fit is refused
