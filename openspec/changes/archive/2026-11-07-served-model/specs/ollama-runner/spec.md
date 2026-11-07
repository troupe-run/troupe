## ADDED Requirements

### Requirement: An answer's other model is a served_model event
When an answer's `model` isn't empty and isn't the model the runner asked for, the runner SHALL send `served_model`
naming it, the first time that model answers in the run, before the answer's `turn` and tool calls, or the `result`
it ends the run with.

#### Scenario: Ollama answers under another name
- **WHEN** the runner asked for `qwen3:0.6b` and an answer's lines say `model` `qwen3:0.6b-q4`
- **THEN** the runner sends `served_model` with `model` `qwen3:0.6b-q4` before that answer's `turn`

#### Scenario: Ollama echoes the name asked for
- **WHEN** every answer says the `model` the runner asked for
- **THEN** the run has no `served_model`
