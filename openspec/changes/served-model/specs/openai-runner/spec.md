## ADDED Requirements

### Requirement: A response's model, when not the runtime's, is a served_model event
When a response's `model` isn't empty and isn't the runtime's model, the runner SHALL send `served_model` naming it,
the first time that model answers in the run, before the response's `turn`, tool calls or `result`. It SHALL NOT also
send a `log` about it. A response with no `model` reports nothing.

#### Scenario: A compatible host answers with another model
- **WHEN** the runtime's model is `gpt-6-luna` and the service's response says `model` `qwen3.5:4b`
- **THEN** the runner sends `served_model` with `model` `qwen3.5:4b` before that response's `turn`, and no `log`
  naming it

#### Scenario: Two responses from the same other model
- **WHEN** both responses of a two-request run say `model` `qwen3.5:4b` and the runtime asked for `gpt-6-luna`
- **THEN** the run has exactly one `served_model`

#### Scenario: The response names the runtime's model
- **WHEN** every response says `model` `gpt-6-luna` and the runtime asked for `gpt-6-luna`
- **THEN** the run has no `served_model` and no `log` about the model
