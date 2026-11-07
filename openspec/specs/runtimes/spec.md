# runtimes Specification

## Purpose
Capability: `cap:config`, `cap:actor-runners`

Names the services runners talk to, once, in config: each runtime's endpoint, default model and credential, resolved
from troupe's defaults, the theatre's config and the person's environment with the source of each value, and the
credential held only by reference and kept out of everything troupe writes.

## Requirements

### Requirement: A runtime is a named service with an endpoint, a model and a credential reference
A runtime SHALL have an `endpoint` (an `http` or `https` URL with no user info, query or fragment), an optional
`model` (non-empty text) and an optional `credential` whose only field, `env`, names an environment variable. Its
name SHALL match the actor-name pattern. Config SHALL never hold a credential's value.

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

### Requirement: A credential can't name troupe's own variables
A runtime's `credential.env` SHALL NOT name a variable that starts with `TROUPE_`, from any source.

#### Scenario: troupe's hand-off variable
- **WHEN** a person sets `runtimes.openai.credential.env=TROUPE_RUNTIME_CREDENTIAL`
- **THEN** it is refused, naming the path and saying a credential can't come from a `TROUPE_` variable

### Requirement: troupe has built-in runtimes
troupe SHALL define the runtimes `openai` (endpoint `https://api.openai.com/v1`, credential from `OPENAI_API_KEY`),
`ollama` (endpoint `http://127.0.0.1:11434`, no credential) and `lm-studio` (endpoint `http://127.0.0.1:1234/v1`, no
credential), as defaults in one named place. No built-in runtime SHALL name a model.

#### Scenario: A built-in needs no config
- **WHEN** config has no `runtimes` and an actor names the runtime `ollama`
- **THEN** the actor is valid, and the runtime's endpoint is `http://127.0.0.1:11434` with source `default`

### Requirement: Theatre config overrides a built-in field by field
A runtime in the theatre's config with a built-in's name SHALL override only the fields it sets. A runtime with any
other name SHALL be defined wholly by config, and SHALL be refused without an `endpoint`.

#### Scenario: Only the model
- **WHEN** config sets only `runtimes.openai.model=gpt-test`
- **THEN** the runtime `openai` has the built-in endpoint and credential variable, and the model `gpt-test` from
  `theatre`

#### Scenario: A new runtime without an endpoint
- **WHEN** config sets only `runtimes.myhost.model=llama`
- **THEN** it is refused, naming `runtimes.myhost.endpoint` as required

### Requirement: The person's environment overrides a runtime's values
`TROUPE_RUNTIME_<NAME>_ENDPOINT`, `TROUPE_RUNTIME_<NAME>_MODEL` and `TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV`, where
`<NAME>` is the runtime's name in capitals with `-` as `_`, SHALL override that runtime's field, with source `env`.
An unset or empty variable SHALL count as absent. They SHALL be read from the session's environment, never a request.

#### Scenario: The endpoint from the environment
- **WHEN** config sets `runtimes.openai.endpoint` and `TROUPE_RUNTIME_OPENAI_ENDPOINT` is `https://proxy.example/v1`
- **THEN** the runtime's endpoint is `https://proxy.example/v1`, with source `env`

#### Scenario: A hyphenated name
- **WHEN** `TROUPE_RUNTIME_LM_STUDIO_MODEL` is `qwen3`
- **THEN** the runtime `lm-studio` has the model `qwen3`, with source `env`

#### Scenario: Empty counts as unset
- **WHEN** `TROUPE_RUNTIME_OLLAMA_ENDPOINT` is the empty string
- **THEN** the runtime `ollama`'s endpoint is its built-in one, with source `default`

### Requirement: A malformed runtime variable is an error
A runtime variable that is set but isn't a value its field accepts SHALL fail the command that resolves the runtime
with `runtime.invalid-value`, naming the variable, the value and what the field accepts. It SHALL NOT fall through.

#### Scenario: An endpoint that isn't a URL
- **WHEN** `TROUPE_RUNTIME_OLLAMA_ENDPOINT` is `localhost:11434` and a person performs an actor on `ollama`
- **THEN** perform fails with `runtime.invalid-value`, naming the variable, the value and that it must be an `http` or
  `https` URL, and nothing is recorded

### Requirement: An actor names its runtime and may set its model
An actor MAY name a `runtime`, which SHALL be a built-in runtime or one in config, and MAY set a `model`. An actor
SHALL name a runtime when its runner requires one, SHALL NOT name one when its runner takes none, and SHALL NOT set a
`model` without a runtime.

#### Scenario: A runtime that doesn't exist
- **WHEN** a person sets `actors.tester.runtime=nowhere`
- **THEN** it is refused, naming the path and the runtimes that exist

#### Scenario: A runner that takes no runtime
- **WHEN** an actor whose runner is `claude-code` names the runtime `openai`
- **THEN** it is refused, naming the path and saying the `claude-code` runner takes no runtime

#### Scenario: A model without a runtime
- **WHEN** a person sets `actors.tester.model=gpt-test` and `tester` names no runtime
- **THEN** it is refused, naming `actors.tester.runtime`

#### Scenario: An Ollama actor without a runtime
- **WHEN** a person sets `actors.tester.runner=ollama` and `tester` names no runtime
- **THEN** it is refused, naming `actors.tester.runtime` and saying the `ollama` runner needs one, listing the
  runtimes there are

### Requirement: The run's model comes from the environment, the actor, then the runtime
A run's model SHALL be the runtime's `TROUPE_RUNTIME_<NAME>_MODEL` when set, else the actor's `model`, else the
runtime's `model` in config, with its source `env`, `actor` or `theatre`. A run whose runtime resolves no model SHALL
be refused with `runtime.no-model` before anything is recorded.

#### Scenario: The actor's model
- **WHEN** config sets `runtimes.openai.model=gpt-a` and `actors.tester.model=gpt-b`, and no variable sets a model
- **THEN** a run of `tester` uses `gpt-b`, with source `actor`

#### Scenario: The person's override wins
- **WHEN** `actors.tester.model` is `gpt-b` and `TROUPE_RUNTIME_OPENAI_MODEL` is `gpt-c`
- **THEN** a run of `tester` uses `gpt-c`, with source `env`

#### Scenario: No model anywhere
- **WHEN** an actor on `openai` sets no model, config sets none, and no variable sets one
- **THEN** perform fails with `runtime.no-model`, naming `actors.tester.model`, `runtimes.openai.model` and
  `TROUPE_RUNTIME_OPENAI_MODEL`, and nothing is recorded

### Requirement: A run's credential is read from the named variable when the run starts
When a run's runtime has a credential, perform SHALL read its value from the variable `credential.env` names, in the
session's environment, when the run starts. An unset or empty variable SHALL refuse the run with
`runtime.credential-unset`, naming the runtime and the variable, before anything is recorded.

#### Scenario: The key isn't set
- **WHEN** an actor on `openai` is performed and `OPENAI_API_KEY` isn't set
- **THEN** perform fails with `runtime.credential-unset`, naming `openai` and `OPENAI_API_KEY`, and nothing is
  recorded

### Requirement: A credential is sent only over HTTPS or to a loopback address
A run whose runtime has a credential SHALL be refused with `runtime.insecure-endpoint`, before anything is recorded,
when its endpoint is `http` and its host isn't `localhost`, a loopback IPv4 address or `::1`.

#### Scenario: Plain HTTP to another host
- **WHEN** a runtime with a credential has the endpoint `http://example.com/v1` and an actor on it is performed
- **THEN** perform fails with `runtime.insecure-endpoint`, naming the endpoint and the runtime, and nothing is
  recorded

#### Scenario: Plain HTTP to this machine
- **WHEN** a runtime with a credential has the endpoint `http://127.0.0.1:8080/v1`
- **THEN** the run starts

### Requirement: A credential too short to mask is refused
A credential whose value is shorter than troupe's named minimum, 8 bytes by default, SHALL refuse the run with
`runtime.credential-too-short`, naming the runtime and the variable but not the value, before anything is recorded.

#### Scenario: A placeholder key
- **WHEN** a runtime's credential variable holds `ollama`
- **THEN** perform fails with `runtime.credential-too-short`, naming the variable and the minimum, and the error holds
  no part of the value

### Requirement: Config get shows a runtime's resolved values and their sources
`troupe config get --resolved` SHALL show every runtime, built-in or in config, and `--resolved runtimes.<name>` one
runtime: each field's value and source (`default`, `theatre` or `env`), and for a credential its variable's name and
whether that variable is set, never its value. `--resolved` with any other path SHALL be refused, naming the path.

#### Scenario: The built-in openai runtime
- **WHEN** config has no runtimes, `OPENAI_API_KEY` is set, and a person runs `troupe config get --resolved
  runtimes.openai`
- **THEN** it shows the endpoint from `default`, no model, and the credential variable `OPENAI_API_KEY` from
  `default`, set

#### Scenario: Another path
- **WHEN** a person runs `troupe config get --resolved actors.tester`
- **THEN** it is refused, naming the path and saying only runtimes have resolved values

### Requirement: A credential's value appears nowhere troupe writes
A credential's value SHALL NOT appear in config's events or projected files, a run's events, its transcript or kept
standard error, the artifacts troupe stores, any error or notice, or any client message, even when the runner sends
it back.

#### Scenario: A runner that echoes the key
- **WHEN** a canary credential is set, and an actor on a scripted runner whose script echoes the credential in a log
  event, a transcript record, its standard error and its result is performed, rehearsed, and shown with
  `config get --resolved`
- **THEN** no file under `.troupe/` or the artifact store, and no message the client received, holds the canary,
  its JSON-escaped form or its base64 form

### Requirement: Options a runner moved to its runtime are refused with the move
An `ollama` actor whose options hold `model` or `endpoint` SHALL be refused wherever config is checked, naming the
option and saying it moved to the actor's runtime. The fix SHALL be one `troupe config set`, built from the actor's
own values, that sets its runtime and model and its options to the rest. It SHALL change no existing runtime.

#### Scenario: The model the audition used to write
- **WHEN** config holds an actor `lead` on `ollama` with `options.model` `qwen3:4b`, no runtime and no other option,
  and a person performs it
- **THEN** perform fails with `config.invalid`, naming `actors.lead.options.model` and saying it moved to the
  runtime, and its fix gives `troupe config set actors.lead.runtime=ollama actors.lead.model=qwen3:4b
  'actors.lead.options={}'`, and nothing is recorded

#### Scenario: The fix run as given
- **WHEN** a person runs the fix that refusal gives
- **THEN** the change is recorded, `lead` names the runtime `ollama` with the model `qwen3:4b` and no options, and
  config breaks no rule

#### Scenario: Other options are kept
- **WHEN** the actor's options are `{"model": "qwen3:4b", "maxTurns": 20}`
- **THEN** the fix sets `'actors.lead.options={"maxTurns":20}'`, keeping `maxTurns`

#### Scenario: The default endpoint
- **WHEN** the actor's options hold `endpoint` `http://127.0.0.1:11434`, the built-in `ollama` runtime's
- **THEN** the fix sets the runtime `ollama`, and defines no runtime

#### Scenario: An endpoint on another host
- **WHEN** the actor's options hold `endpoint` `http://gpu-box.local:11434`
- **THEN** the fix sets `runtimes.<name>.endpoint=http://gpu-box.local:11434` and `actors.lead.runtime=<name>`, says
  to choose the name, and sets nothing under `runtimes.ollama`

#### Scenario: An endpoint holding a password
- **WHEN** the actor's options hold `endpoint` `http://user:secret@127.0.0.1:11434`
- **THEN** the refusal and its fix hold no part of `secret`

#### Scenario: An unrelated change
- **WHEN** config holds such an actor and a person sets a value on another actor
- **THEN** it is refused with the same rule and fix, since the change would leave config breaking it
