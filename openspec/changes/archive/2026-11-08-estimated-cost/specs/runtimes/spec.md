## MODIFIED Requirements

### Requirement: troupe has built-in runtimes
troupe SHALL define the runtimes `openai` (endpoint `https://api.openai.com/v1`, credential from `OPENAI_API_KEY`),
`ollama` (endpoint `http://127.0.0.1:11434`, no credential) and `lm-studio` (endpoint `http://127.0.0.1:1234/v1`, no
credential), as defaults in one named place. No built-in runtime SHALL name a model or a price.

#### Scenario: A built-in needs no config
- **WHEN** config has no `runtimes` and an actor names the runtime `ollama`
- **THEN** the actor is valid, and the runtime's endpoint is `http://127.0.0.1:11434` with source `default`

#### Scenario: No built-in price
- **WHEN** config has no `runtimes` and an actor on `openai` with the model `gpt-test` is performed
- **THEN** the run has no price, and its `run/start` carries none

### Requirement: Config get shows a runtime's resolved values and their sources
`troupe config get --resolved` SHALL show every runtime, built-in or in config, and `--resolved runtimes.<name>` one
runtime: each field's value and source (`default`, `theatre` or `env`), and for a credential its variable's name and
whether that variable is set, never its value. `--resolved` with any other path SHALL be refused, naming the path.

#### Scenario: The built-in openai runtime
- **WHEN** config has no runtimes, `OPENAI_API_KEY` is set, and a person runs `troupe config get --resolved
  runtimes.openai`
- **THEN** it shows the endpoint from `default`, no model, and the credential variable `OPENAI_API_KEY` from
  `default`, set

#### Scenario: The price of the runtime's model
- **WHEN** config sets `runtimes.openai.model=gpt-test` and a price for `gpt-test`, and a person runs `troupe config
  get --resolved runtimes.openai`
- **THEN** it shows that price with source `theatre`

#### Scenario: Another path
- **WHEN** a person runs `troupe config get --resolved actors.tester`
- **THEN** it is refused, naming the path and saying only runtimes have resolved values

## ADDED Requirements

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
