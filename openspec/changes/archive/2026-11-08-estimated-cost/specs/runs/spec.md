## MODIFIED Requirements

### Requirement: A run's start records its runtime and where each value came from
When an actor names a runtime, the run's start SHALL record the runtime's name, its endpoint and model, each with its
source, when it has a credential, the variable's name and its source, and when the run's model has a price, that price
with its source. It SHALL NOT record the credential's value.

#### Scenario: A run on a theatre-chosen endpoint
- **WHEN** config sets `runtimes.openai.endpoint=https://gateway.example/v1` and an actor on `openai` is performed
- **THEN** the run's start records the endpoint `https://gateway.example/v1` with source `theatre`, and the variable
  `OPENAI_API_KEY` with source `default`

#### Scenario: A run on a priced model
- **WHEN** config prices `gpt-test` on `openai` and an actor on `openai` with the model `gpt-test` is performed
- **THEN** the run's start records that price with source `theatre`, the same price its `run/start` carried

#### Scenario: A run with no runtime
- **WHEN** an actor that names no runtime is performed
- **THEN** the run's start has no `runtime` field

### Requirement: A rehearsal shows the run's runtime
A rehearsed `perform` SHALL show the runtime the run would use, with each value's source, whether its credential's
variable is set, and the price of its model when it has one, and SHALL refuse what perform would refuse about the
runtime.

#### Scenario: A rehearsal on openai
- **WHEN** a person rehearses an actor on `openai` and `OPENAI_API_KEY` is set
- **THEN** the rehearsal shows the endpoint, the model and the variable `OPENAI_API_KEY`, set, each with its source,
  and no part of the key

#### Scenario: A rehearsal on a priced model
- **WHEN** a person rehearses an actor on `openai` whose model config prices
- **THEN** the rehearsal shows that price with source `theatre`
