## ADDED Requirements

### Requirement: The service comes from the run's runtime
The runner SHALL take its endpoint and model from the runtime troupe resolves for the run (spec: runtimes), and from
nowhere else. Its options SHALL hold no endpoint or model, and no endpoint or model SHALL be written in the runner. A
`run/start` with no runtime SHALL be refused with `ollama.no-runtime`, whose fix says to name a runtime for the actor,
and no request SHALL be sent.

#### Scenario: The runtime's endpoint and model
- **WHEN** a run's runtime has the endpoint `http://gpu-box.local:11434` and the model `qwen3:4b`
- **THEN** the runner's requests go to that host, and every request asks for `qwen3:4b`

#### Scenario: The built-in runtime
- **WHEN** a run's runtime is troupe's built-in `ollama`, with no endpoint set in config or the environment
- **THEN** the runner's requests go to `http://127.0.0.1:11434`

#### Scenario: A run without a runtime
- **WHEN** a `run/start` carries no runtime
- **THEN** `run/start` is refused with `ollama.no-runtime`, whose fix says to name a runtime for the actor, and no
  request is sent

#### Scenario: An endpoint or model in the options
- **WHEN** a `run/start`'s options hold `endpoint` or `model`
- **THEN** `run/start` is refused with `ollama.unknown-option`, naming the option

### Requirement: The runtime's endpoint is one the runner can use
The runner SHALL refuse a runtime whose endpoint holds a user name or password, a path other than `/`, a query, a
fragment, a port above 65535, or a host name part that's empty or over 63 characters, with `ollama.invalid-runtime`
naming `runtime.endpoint`, before any request is sent. The fix SHALL name the runtime's config path and its
`TROUPE_RUNTIME_<NAME>_ENDPOINT` variable.

#### Scenario: A path in the endpoint
- **WHEN** a run's runtime `ollama` has the endpoint `http://127.0.0.1:11434/v1`
- **THEN** `run/start` is refused with `ollama.invalid-runtime`, naming `runtime.endpoint`, and its fix names
  `runtimes.ollama.endpoint` and `TROUPE_RUNTIME_OLLAMA_ENDPOINT`

#### Scenario: A port or host name no connection could use
- **WHEN** the runtime's endpoint is `http://127.0.0.1:99999` or `http://a..b:11434`
- **THEN** `run/start` is refused with `ollama.invalid-runtime`, naming `runtime.endpoint`, and the runner keeps
  serving

#### Scenario: Credentials in the endpoint
- **WHEN** the runtime's endpoint is `http://user:secret@127.0.0.1:11434`
- **THEN** `run/start` is refused with `ollama.invalid-runtime`, naming `runtime.endpoint`, and its message doesn't
  hold `secret`

### Requirement: A runtime with a credential is refused
The runner SHALL send no credential. A `run/start` whose `runtime.credential` is `true` SHALL be refused with
`ollama.credential-unsupported`, naming the runtime, before any request is sent. The runner SHALL NOT read
`TROUPE_RUNTIME_CREDENTIAL`, and the error SHALL hold no part of its value.

#### Scenario: A runtime that names a key
- **WHEN** a run's runtime has `credential` `true`, and `TROUPE_RUNTIME_CREDENTIAL` holds a canary
- **THEN** `run/start` is refused with `ollama.credential-unsupported`, naming the runtime, no request is sent, and
  the error holds no part of the canary

## MODIFIED Requirements

### Requirement: The runner identifies itself as ollama
The runner SHALL answer `initialize` with the name `ollama` and its package's version. Its `init` event SHALL name
the runner the same way, the engine `ollama` with the version Ollama reports and the model from the run's runtime, the
seven SDK tools, and `effects` `checked`.

#### Scenario: Init for a run
- **WHEN** a run starts with a runtime whose model is `qwen3:4b`, against an Ollama that reports version `0.12.6`
- **THEN** the `init` event's engine is `{"name": "ollama", "version": "0.12.6", "model": "qwen3:4b"}`, its tools are
  `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Delete` and `Move`, and its `effects` is `checked`

### Requirement: The runner's options are closed
`run/start` options SHALL be an object with optionally `maxTurns`, `contextLength`, `temperature`, `seed` and `think`.
An option the runner doesn't define SHALL be refused with `ollama.unknown-option`, and a value of the wrong shape with
`ollama.invalid-options`, each naming the option in `details.where`, and no run starts.

#### Scenario: An unknown option
- **WHEN** the options hold `troupeConformanceUnknownOption`
- **THEN** `run/start` is refused with `ollama.unknown-option`, whose `details.where` names the option

#### Scenario: No model
- **WHEN** the options are `{}`, so they name no model, and the run's runtime names `qwen3:4b`
- **THEN** the run starts, asking for `qwen3:4b`, with the runner's defaults for every option

#### Scenario: A malformed value
- **WHEN** `maxTurns` is `0` or `think` is `"maximum"`
- **THEN** `run/start` is refused with `ollama.invalid-options`, naming the option, and its fix names what is valid

### Requirement: The runner checks the engine before it acknowledges the run
Before answering `run/start`, the runner SHALL ask Ollama for its version and for the model, within a named time
limit. It SHALL refuse the run with `ollama.unreachable` when Ollama doesn't answer, `runner.requirement-unmet` when
Ollama's version doesn't meet its requirements, `ollama.model-not-found` when the model isn't there, and
`ollama.model-without-tools` when it can't call tools.

#### Scenario: A run start the runner can't carry out
- **WHEN** a `run/start`'s scratch directory doesn't exist
- **THEN** it is refused with `runner.invalid-params`, and no run is acknowledged

#### Scenario: Ollama isn't running
- **WHEN** nothing listens at the runtime's endpoint
- **THEN** `run/start` is refused with `ollama.unreachable`, naming the endpoint, and the fix says to start Ollama or
  to set the runtime's endpoint, naming `runtimes.<name>.endpoint` and `TROUPE_RUNTIME_<NAME>_ENDPOINT` for the run's
  runtime

#### Scenario: An Ollama too old for the runner
- **WHEN** Ollama reports version `0.12.5`
- **THEN** `run/start` is refused with `runner.requirement-unmet`, naming `ollama`, the version wanted and `0.12.5`,
  and the fix says to upgrade Ollama

#### Scenario: A version the runner can't read
- **WHEN** Ollama reports a version that isn't numbers separated by dots, with an optional suffix
- **THEN** `run/start` is refused with `runner.requirement-unmet`, naming what Ollama reported

#### Scenario: A model that isn't pulled
- **WHEN** Ollama answers that `qwen3:4b` isn't there
- **THEN** `run/start` is refused with `ollama.model-not-found`, and the fix names `ollama pull qwen3:4b`

#### Scenario: A model that can't call tools
- **WHEN** Ollama's description of the model doesn't list the `tools` capability
- **THEN** `run/start` is refused with `ollama.model-without-tools`, naming the model

### Requirement: The runner conforms to the contract
The Ollama runner SHALL pass troupe's conformance suite against a fake Ollama endpoint.

#### Scenario: The conformance suite
- **WHEN** the conformance suite runs against the Ollama runner, with a runtime naming a fake endpoint that serves a
  short successful run, and no credential
- **THEN** every check passes

## REMOVED Requirements

### Requirement: The endpoint is an option with a named default
**Reason**: The endpoint and the model come from the run's runtime (spec: runtimes, #278), the one place a service is
defined. The built-in `ollama` runtime holds the default endpoint, `http://127.0.0.1:11434`, so the runner no longer
has one of its own. The endpoint's rules move to "The runtime's endpoint is one the runner can use".
**Migration**: Name a runtime for the actor and move its model there, in one change, such as
`troupe config set actors.<name>.runtime=ollama actors.<name>.model=qwen3:4b 'actors.<name>.options={}'`. Point it at
another host with `runtimes.ollama.endpoint`, a runtime of the actor's own, or `TROUPE_RUNTIME_OLLAMA_ENDPOINT`.
Config refuses an actor still holding the old options, with the exact command for it (spec: runtimes).
