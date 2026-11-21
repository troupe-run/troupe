## ADDED Requirements

### Requirement: A runtime can name its engine
A runtime SHALL accept an optional `engine`, naming what serves its endpoint: one of `claude`, `lm-studio`, `ollama` and
`llama.cpp`, defined once in the protocol's runtime schema. Any other value SHALL be refused, naming the path and the
values it takes. A runtime without one has no engine, and troupe SHALL NOT infer one from its endpoint. A runner that
doesn't use the engine SHALL ignore it.

#### Scenario: A local engine named
- **WHEN** a person runs `troupe config set runtimes.lm-studio-messages.endpoint=http://127.0.0.1:1234
  runtimes.lm-studio-messages.engine=lm-studio`
- **THEN** config records the engine `lm-studio`

#### Scenario: An engine troupe doesn't name
- **WHEN** a person sets `runtimes.lm-studio-messages.engine` to `LM Studio`
- **THEN** it is refused, naming the path and the engines it takes

#### Scenario: No engine named
- **WHEN** config defines `runtimes.gateway.endpoint=https://api.anthropic.com` and no engine
- **THEN** the runtime `gateway` has no engine, though its endpoint is Claude's

## MODIFIED Requirements

### Requirement: The person's environment overrides a runtime's values
`TROUPE_RUNTIME_<NAME>_ENDPOINT`, `TROUPE_RUNTIME_<NAME>_MODEL`, `TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV` and
`TROUPE_RUNTIME_<NAME>_ENGINE`, where
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

#### Scenario: The engine from the environment
- **WHEN** config defines `runtimes.lm-studio-messages.endpoint=http://127.0.0.1:1234` with no engine, and
  `TROUPE_RUNTIME_LM_STUDIO_MESSAGES_ENGINE` is `lm-studio`
- **THEN** the runtime's engine is `lm-studio`, with source `env`

### Requirement: A malformed runtime variable is an error
A runtime variable that is set but isn't a value its field accepts SHALL fail the command that resolves the runtime
with `runtime.invalid-value`, naming the variable and what the field accepts, and never the value, in its problem, its
fix or its details. It SHALL NOT fall through.

#### Scenario: An endpoint that isn't a URL
- **WHEN** `TROUPE_RUNTIME_OLLAMA_ENDPOINT` is `localhost:11434` and a person performs an actor on `ollama`
- **THEN** perform fails with `runtime.invalid-value`, naming the variable and that it must be an `http` or `https`
  URL, the error holds no part of `localhost:11434`, and nothing is recorded

#### Scenario: A key where a variable's name should be
- **WHEN** `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV` holds a key, `sk-test q7ZxW9pL`, rather than a variable's name, and
  a person runs `troupe config get --resolved runtimes.openai`
- **THEN** it fails with `runtime.invalid-value`, naming `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV` and that it must be a
  variable's name, and nothing the client receives holds the key

#### Scenario: An endpoint carrying a password
- **WHEN** `TROUPE_RUNTIME_OLLAMA_ENDPOINT` is `https://user:hunter2-secret@example.com/v1`
- **THEN** resolving `ollama` fails with `runtime.invalid-value`, and the error holds neither the URL nor
  `hunter2-secret`

#### Scenario: An engine troupe doesn't name
- **WHEN** `TROUPE_RUNTIME_OLLAMA_ENGINE` is `lmstudio`
- **THEN** resolving `ollama` fails with `runtime.invalid-value`, naming the variable and the engines it takes:
  `claude`, `lm-studio`, `ollama` and `llama.cpp`

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

#### Scenario: The engine and its source
- **WHEN** config has no runtimes and a person runs `troupe config get --resolved runtimes.anthropic`
- **THEN** it shows the engine `claude` with source `default`

#### Scenario: Another path
- **WHEN** a person runs `troupe config get --resolved actors.tester`
- **THEN** it is refused, naming the path and saying only runtimes have resolved values

### Requirement: troupe defines its built-in runtimes in one place
troupe SHALL define the runtimes `openai` (endpoint `https://api.openai.com/v1`, credential from `OPENAI_API_KEY`),
`anthropic` (endpoint `https://api.anthropic.com`, credential from `ANTHROPIC_API_KEY`, engine `claude`), `ollama`
(endpoint `http://127.0.0.1:11434`, no credential, engine `ollama`) and `mistralrs` (in-process: no endpoint, no
credential), as defaults in one named place. No built-in runtime SHALL name a model or a price.

#### Scenario: A built-in needs no config
- **WHEN** config has no `runtimes` and an actor names the runtime `ollama`
- **THEN** the actor is valid, and the runtime's endpoint is `http://127.0.0.1:11434` with source `default`

#### Scenario: No built-in price
- **WHEN** config has no `runtimes` and an actor on `openai` with the model `gpt-test` is performed
- **THEN** the run has no price, and its `run/start` carries none

#### Scenario: LM Studio has no built-in
- **WHEN** config has no `runtimes` and troupe resolves the runtime `lm-studio`
- **THEN** it is refused as a runtime that doesn't exist, naming the runtimes that do: `anthropic`, `mistralrs`,
  `ollama` and `openai`

#### Scenario: Claude's API is a built-in
- **WHEN** config has no `runtimes` and a person runs `troupe config get --resolved runtimes.anthropic`
- **THEN** it shows the endpoint `https://api.anthropic.com`, the credential variable `ANTHROPIC_API_KEY` and the
  engine `claude`, each from `default`, and no model

#### Scenario: The in-process built-in
- **WHEN** config has no `runtimes`, `TROUPE_RUNTIME_MISTRALRS_MODEL` is `/models/qwen3-0.6b.gguf`, and a person runs
  `troupe config get --resolved runtimes.mistralrs`
- **THEN** it shows no endpoint and no credential, and the model `/models/qwen3-0.6b.gguf` from `env`
