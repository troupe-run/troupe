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
`anthropic` (endpoint `https://api.anthropic.com`, credential from `ANTHROPIC_API_KEY`), `ollama` (endpoint
`http://127.0.0.1:11434`, no credential) and `lm-studio` (endpoint `http://127.0.0.1:1234`, no credential), as
defaults in one named place. No built-in runtime SHALL name a model or a price.

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
`runtime.credential-unset`, naming the runtime and the variable (as "A refusal never repeats a credential variable's
name taken from the environment" says), before anything is recorded.

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
`runtime.credential-too-short`, naming the runtime and the variable (as "A refusal never repeats a credential
variable's name taken from the environment" says) but not the value, before anything is recorded.

#### Scenario: A placeholder key
- **WHEN** a runtime's credential variable holds `ollama`
- **THEN** perform fails with `runtime.credential-too-short`, naming the variable and the minimum, and the error holds
  no part of the value

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

### Requirement: A refusal never repeats a credential variable's name taken from the environment
When a run's credential variable is named by `TROUPE_RUNTIME_<NAME>_CREDENTIAL_ENV`, `runtime.credential-unset`,
`runtime.credential-malformed` and `runtime.credential-too-short` SHALL name that `TROUPE_RUNTIME_` variable instead of
the name it holds, and SHALL hold no part of that name. A name from the theatre's config or a built-in runtime SHALL be
named as it is.

#### Scenario: A key where the variable's name should be
- **WHEN** `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV` is `a3f9c2e17b4d8e05f6a1`, no variable of that name is set, and an
  actor on `openai` is performed
- **THEN** perform fails with `runtime.credential-unset`, naming `openai` and `TROUPE_RUNTIME_OPENAI_CREDENTIAL_ENV`,
  the error holds no part of `a3f9c2e17b4d8e05f6a1`, and nothing is recorded

#### Scenario: A name from config
- **WHEN** config sets `runtimes.openai.credential.env=MY_KEY`, `MY_KEY` isn't set, and an actor on `openai` is
  performed
- **THEN** perform fails with `runtime.credential-unset`, naming `MY_KEY`

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

### Requirement: A runtime can price its models
A runtime in config MAY hold `prices`, a map from a model's name, as the service names it, to that model's price (spec:
runner-protocol, "A price is in US dollars per million tokens"). A price that isn't one SHALL be refused, naming its
path and what a price holds.

#### Scenario: Pricing a model
- **WHEN** a person runs `troupe config set runtimes.openai.prices.gpt-test='{"input": 2, "output": 8}'`
- **THEN** config records that price for `gpt-test` on `openai`

#### Scenario: A price with an unknown field
- **WHEN** a person sets `runtimes.openai.prices.gpt-test` to `{"input": 2, "output": 8, "currency": "EUR"}`
- **THEN** it is refused, naming the path and saying a price holds only `input`, `output`, `cacheRead` and
  `cacheWrite`

#### Scenario: A model's name with a dot
- **WHEN** a person sets `runtimes.openai.prices` to a map whose key is `gpt-4.1`, given as JSON
- **THEN** config records that price for the model `gpt-4.1`

### Requirement: A run's price is the price of its model
A run's price SHALL be the price its runtime's `prices` holds for the run's model, matched exactly, with source
`theatre`. A run whose model has no price SHALL have none. No environment variable SHALL set a price.

#### Scenario: The actor's model is priced
- **WHEN** config prices `gpt-a` and `gpt-b` on `openai`, and a run of `tester` uses `gpt-b` from the actor
- **THEN** the run's price is `gpt-b`'s

#### Scenario: The model from the environment has no price
- **WHEN** config prices only `gpt-b`, and `TROUPE_RUNTIME_OPENAI_MODEL` makes a run use `gpt-c`
- **THEN** the run has no price

#### Scenario: A near match
- **WHEN** config prices `gpt-b` and a run uses `gpt-b-2026-01-01`
- **THEN** the run has no price

### Requirement: An actor's runtime fits its runner
Config SHALL refuse an actor whose runtime doesn't fit its runner, judged from the runtime's built-in and theatre
values: a credential the runner never sends, an endpoint path it can't use (a final `/v1`, for one that adds it),
`https` where it needs plain `http`, or another runner's built-in. The error SHALL name the actor's `runtime` path,
the runner, the runtime, why, and the runtimes that fit. A change to a runtime that makes an actor on it unfit SHALL
be refused the same way.

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
