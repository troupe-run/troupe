# Spec Delta

## MODIFIED Requirements

### Requirement: Run start carries the run's runtime
When an actor names a runtime, `run/start` SHALL carry `runtime`: its `name`, `endpoint` (only when the runtime has
one) and `model` as troupe resolved them, `credential`, `true` when the runner's environment holds the credential and
`false` when the runtime has none, and `price` when troupe has a price for the run's model (spec: runtimes). It SHALL
NOT carry the credential's value or its variable's name. Without a runtime it is absent.

#### Scenario: A runtime with a credential
- **WHEN** troupe starts a run on the runtime `openai` with the model `gpt-test`, and config has no price for it
- **THEN** `run/start` carries `runtime` with `name` `openai`, the endpoint, `model` `gpt-test` and `credential`
  `true`, and nothing else

#### Scenario: A runtime with a price for the run's model
- **WHEN** troupe starts a run on the runtime `openai` with the model `gpt-test`, and config prices `gpt-test` at 2
  dollars per million input tokens and 8 per million output tokens
- **THEN** `run/start`'s `runtime` carries `price` `{"input": 2, "output": 8}`

#### Scenario: No runtime
- **WHEN** troupe starts a run for an actor that names no runtime
- **THEN** `run/start` has no `runtime` field, rather than a null

#### Scenario: The value isn't in run start
- **WHEN** a `run/start` with a `runtime` is validated against the contract's schema
- **THEN** the schema has no field for a credential's value or its variable's name

#### Scenario: An in-process runtime
- **WHEN** troupe starts a run on the runtime `mistralrs` with the model `/models/qwen3-0.6b.gguf`
- **THEN** `run/start` carries `runtime` with `name` `mistralrs`, that `model` and `credential` `false`, and no
  `endpoint` field, rather than a null
