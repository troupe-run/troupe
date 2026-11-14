# Spec Delta

## MODIFIED Requirements

### Requirement: A runtime is a named service with an endpoint, a model and a credential reference
A runtime SHALL have an `endpoint` (an `http` or `https` URL with no user info, query or fragment), unless it is an
in-process runtime, which has none; an optional `model` (non-empty text); and an optional `credential` whose only
field, `env`, names an environment variable. Its name SHALL match the actor-name pattern. Config SHALL never hold a
credential's value.

#### Scenario: A credential by reference
- **WHEN** a person runs `troupe config set runtimes.openai.credential.env=MY_OPENAI_KEY`
- **THEN** config records the name `MY_OPENAI_KEY`, and nothing else about the key

#### Scenario: A field the runtime doesn't have
- **WHEN** a person sets `runtimes.openai.credential.value`
- **THEN** it is refused, naming the path and saying a runtime's credential holds only `env`, a variable's name

#### Scenario: An endpoint with user info
- **WHEN** a person sets `runtimes.myhost.endpoint` to `https://user:secret@example.com/v1`
- **THEN** it is refused, naming the path and saying an endpoint can't carry user info, a query or a fragment

#### Scenario: A variable name that isn't one
- **WHEN** a person sets `runtimes.openai.credential.env` to `MY KEY`
- **THEN** it is refused, naming the path and the pattern a variable's name must match

### Requirement: troupe has built-in runtimes
troupe SHALL define the runtimes `openai` (endpoint `https://api.openai.com/v1`, credential from `OPENAI_API_KEY`),
`anthropic` (endpoint `https://api.anthropic.com`, credential from `ANTHROPIC_API_KEY`), `ollama` (endpoint
`http://127.0.0.1:11434`, no credential), `lm-studio` (endpoint `http://127.0.0.1:1234`, no credential) and
`mistralrs` (in-process: no endpoint, no credential), as defaults in one named place. No built-in runtime SHALL name
a model or a price.

#### Scenario: A built-in needs no config
- **WHEN** config has no `runtimes` and an actor names the runtime `ollama`
- **THEN** the actor is valid, and the runtime's endpoint is `http://127.0.0.1:11434` with source `default`

#### Scenario: No built-in price
- **WHEN** config has no `runtimes` and an actor on `openai` with the model `gpt-test` is performed
- **THEN** the run has no price, and its `run/start` carries none

#### Scenario: LM Studio's built-in is its server root
- **WHEN** config has no `runtimes` and a person runs `troupe config get --resolved runtimes.lm-studio`
- **THEN** it shows the endpoint `http://127.0.0.1:1234` from `default`, the base LM Studio's own API lives under

#### Scenario: Claude's API is a built-in
- **WHEN** config has no `runtimes` and a person runs `troupe config get --resolved runtimes.anthropic`
- **THEN** it shows the endpoint `https://api.anthropic.com` and the credential variable `ANTHROPIC_API_KEY`, each
  from `default`, and no model

#### Scenario: The in-process built-in
- **WHEN** config has no `runtimes`, `TROUPE_RUNTIME_MISTRALRS_MODEL` is `/models/qwen3-0.6b.gguf`, and a person runs
  `troupe config get --resolved runtimes.mistralrs`
- **THEN** it shows no endpoint and no credential, and the model `/models/qwen3-0.6b.gguf` from `env`


### Requirement: An actor's runtime fits its runner
Config SHALL refuse an actor whose runtime doesn't fit its runner, judged from the runtime's built-in and theatre
values: a credential the runner never sends, an endpoint path it can't use (a final `/v1`, for one that adds it),
an endpoint it doesn't take or none where it needs one, `https` where it needs plain `http`, or another runner's
built-in. The error SHALL name the actor's `runtime` path, the runner, the runtime, why, and the runtimes that fit. A
change to a runtime that makes an actor on it unfit SHALL be refused the same way.

#### Scenario: An Ollama actor on a runtime with a credential
- **WHEN** a person sets `actors.tester.runner=ollama` and `actors.tester.runtime=openai`
- **THEN** it is refused, naming `actors.tester.runtime`, the `ollama` runner and the runtime `openai`, saying the
  runner sends no credential and `openai` has one, and listing `ollama` as a runtime that fits

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
  `https` one, and listing `lm-studio` as a runtime that fits

#### Scenario: Another runner's built-in of the same shape
- **WHEN** a person sets `actors.tester.runner=ollama` and `actors.tester.runtime=lm-studio`
- **THEN** it is refused, saying `lm-studio` is troupe's built-in for the `lm-studio` runner, though its endpoint has
  the shape the `ollama` runner needs, and listing `ollama` as a runtime that fits

#### Scenario: A runtime of your own of the same shape
- **WHEN** config defines `runtimes.gpu-box.endpoint=http://10.0.0.5:1234`, and an `ollama` actor or an `lm-studio`
  actor names `gpu-box`
- **THEN** it is accepted, since troupe can't tell which engine a runtime of your own serves

#### Scenario: Every runtime fits a runner that takes any
- **WHEN** a `scripted` actor names any runtime there is
- **THEN** no fit is refused

#### Scenario: An Anthropic actor on an endpoint ending in /v1
- **WHEN** config defines `runtimes.claude-v1.endpoint=https://api.anthropic.com/v1`, and a person sets
  `actors.tester.runner=anthropic` and `actors.tester.runtime=claude-v1`
- **THEN** it is refused, saying the `anthropic` runner adds `/v1` below its endpoint itself and `claude-v1`'s
  already ends in `/v1`, naming `https://api.anthropic.com` as the base to use, and listing `anthropic` as a runtime
  that fits

#### Scenario: An Anthropic actor on a gateway's own path
- **WHEN** config defines `runtimes.gateway.endpoint=https://gateway.example/anthropic`, and an `anthropic` actor
  names `gateway`
- **THEN** it is accepted

#### Scenario: An in-process actor on a served runtime
- **WHEN** a person sets `actors.tester.runner=mistralrs` and `actors.tester.runtime=ollama`
- **THEN** it is refused, saying the `mistralrs` runner runs its model in process and takes a runtime with no
  endpoint, and listing `mistralrs` as a runtime that fits

#### Scenario: A served actor on the in-process runtime
- **WHEN** a person sets `actors.tester.runner=ollama` and `actors.tester.runtime=mistralrs`
- **THEN** it is refused, saying the `ollama` runner needs an endpoint and `mistralrs` has none, and listing `ollama`
  as a runtime that fits


## ADDED Requirements

### Requirement: An in-process runtime takes no endpoint
An in-process runtime SHALL NOT be given an endpoint. Setting `runtimes.<name>.endpoint` for one SHALL be refused,
naming the path, and a `TROUPE_RUNTIME_<NAME>_ENDPOINT` set for one SHALL fail the command that resolves it with
`runtime.invalid-value`, naming the variable, each saying the runtime runs its model in the runner's own process.

#### Scenario: An endpoint in config
- **WHEN** a person sets `runtimes.mistralrs.endpoint=http://127.0.0.1:1234`
- **THEN** it is refused, naming `runtimes.mistralrs.endpoint` and saying `mistralrs` runs its model in process

#### Scenario: An endpoint from the environment
- **WHEN** `TROUPE_RUNTIME_MISTRALRS_ENDPOINT` is set and a person performs an actor on `mistralrs`
- **THEN** perform fails with `runtime.invalid-value`, naming `TROUPE_RUNTIME_MISTRALRS_ENDPOINT`, and nothing is
  recorded
