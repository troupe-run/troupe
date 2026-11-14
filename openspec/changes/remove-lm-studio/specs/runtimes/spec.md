## MODIFIED Requirements

### Requirement: The person's environment overrides a runtime's values
`TROUPE_RUNTIME_<NAME>_ENDPOINT`, `TROUPE_RUNTIME_<NAME>_MODEL` and `TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV`, where
`<NAME>` is the runtime's name in capitals with `-` as `_`, SHALL override that runtime's field, with source `env`.
An unset or empty variable SHALL count as absent. They SHALL be read from the session's environment, never a request.

#### Scenario: The endpoint from the environment
- **WHEN** config sets `runtimes.openai.endpoint` and `TROUPE_RUNTIME_OPENAI_ENDPOINT` is `https://proxy.example/v1`
- **THEN** the runtime's endpoint is `https://proxy.example/v1`, with source `env`

#### Scenario: A hyphenated name
- **WHEN** config defines `runtimes.gpu-box.endpoint=http://10.0.0.5:11434` and `TROUPE_RUNTIME_GPU_BOX_MODEL` is
  `qwen3`
- **THEN** the runtime `gpu-box` has the model `qwen3`, with source `env`

#### Scenario: Empty counts as unset
- **WHEN** `TROUPE_RUNTIME_OLLAMA_ENDPOINT` is the empty string
- **THEN** the runtime `ollama`'s endpoint is its built-in one, with source `default`

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
  runtimes that fit it: `ollama`, and not `openai`

#### Scenario: No runtime fits
- **WHEN** an `ollama` actor names no runtime, and config overrides the built-in `ollama` with a credential
- **THEN** it is refused, saying no runtime there is fits the `ollama` runner, and how to define one

### Requirement: An actor's runtime fits its runner
Config SHALL refuse an actor whose runtime doesn't fit its runner, judged from the runtime's built-in and theatre
values: a credential the runner never sends, an endpoint path it can't use, or another runner's built-in, whatever its
shape. The error SHALL name the actor's `runtime` path, the runner, the runtime, why, and the runtimes that fit. A
change to a runtime that makes an actor on it unfit SHALL be refused the same way.

#### Scenario: An Ollama actor on a runtime with a credential
- **WHEN** a person sets `actors.tester.runner=ollama` and `actors.tester.runtime=openai`
- **THEN** it is refused, naming `actors.tester.runtime`, the `ollama` runner and the runtime `openai`, saying the
  runner sends no credential and `openai` has one, and listing `ollama` as a runtime that fits

#### Scenario: An Ollama actor on an endpoint with a path
- **WHEN** config defines `runtimes.local-openai.endpoint=http://127.0.0.1:1234/v1`, and a person sets
  `actors.tester.runner=ollama` and `actors.tester.runtime=local-openai`
- **THEN** it is refused, saying the `ollama` runner needs an endpoint with no path and `local-openai`'s has one

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
- **THEN** it is refused with `runner.unknown`, since troupe has no `lm-studio` runner, and not for the endpoint's
  scheme: no runner is limited to plain `http`

#### Scenario: Another runner's built-in of the same shape
- **WHEN** another runner's built-in runtime has an endpoint of the shape the `ollama` runner needs, and a person sets
  `actors.tester.runner=ollama` and `actors.tester.runtime` to that built-in
- **THEN** it is refused, saying the runtime is troupe's built-in for the other runner, though its endpoint has the
  shape the `ollama` runner needs, and listing `ollama` as a runtime that fits

#### Scenario: A runtime of your own of the same shape
- **WHEN** config defines `runtimes.gpu-box.endpoint=http://10.0.0.5:1234`, and an `ollama` actor names `gpu-box`
- **THEN** it is accepted, since troupe can't tell which engine a runtime of your own serves

#### Scenario: Every runtime fits a runner that takes any
- **WHEN** a `scripted` actor names any runtime there is
- **THEN** no fit is refused

## ADDED Requirements

### Requirement: troupe defines its built-in runtimes in one place
troupe SHALL define the runtimes `openai` (endpoint `https://api.openai.com/v1`, credential from `OPENAI_API_KEY`) and
`ollama` (endpoint `http://127.0.0.1:11434`, no credential), as defaults in one named place. No built-in runtime SHALL
name a model or a price.

#### Scenario: A built-in needs no config
- **WHEN** config has no `runtimes` and an actor names the runtime `ollama`
- **THEN** the actor is valid, and the runtime's endpoint is `http://127.0.0.1:11434` with source `default`

#### Scenario: No built-in price
- **WHEN** config has no `runtimes` and an actor on `openai` with the model `gpt-test` is performed
- **THEN** the run has no price, and its `run/start` carries none

#### Scenario: LM Studio has no built-in
- **WHEN** config has no `runtimes` and troupe resolves the runtime `lm-studio`
- **THEN** it is refused as a runtime that doesn't exist, naming the runtimes that do: `ollama` and `openai`

## REMOVED Requirements

### Requirement: troupe has built-in runtimes
**Reason**: The built-in `lm-studio` runtime is removed with the LM Studio runner (#413; owner, 2026-11-14), so the
scenario that LM Studio's built-in is its server root no longer holds. The requirement is re-added as "troupe defines its
built-in runtimes in one place", without `lm-studio` or that scenario, and with one saying `lm-studio` is no longer
a runtime.
**Migration**: A config that relied on the built-in `lm-studio` defines `runtimes.lm-studio.endpoint` itself. LM
Studio users define a runtime of their own for the anthropic runner (#415).
