## ADDED Requirements

### Requirement: An assistant message's other model is a served_model event
When an `assistant` record's `message.model` isn't empty, isn't `<synthetic>` (Claude Code's mark on a message it made
itself) and isn't the model `system/init` named, the runner SHALL send `served_model` naming it, the first time that
model appears in the run, before the record's `turn` and tool calls. A subagent's messages count the same.

#### Scenario: A fallback model answers
- **WHEN** `system/init` names `claude-opus-5-5` and an assistant record's `message.model` is `claude-sonnet-5-5`
- **THEN** the runner sends `served_model` with `model` `claude-sonnet-5-5`, then that record's `turn` and tool calls

#### Scenario: A message Claude Code made itself
- **WHEN** an assistant record's `message.model` is `<synthetic>`
- **THEN** no `served_model` is sent for it

#### Scenario: Init's own model
- **WHEN** every assistant record's `message.model` is the model `system/init` named
- **THEN** the run has no `served_model`

### Requirement: The result's other models are served_model events before it
For each model named in the `result` record's `modelUsage` that isn't `<synthetic>`, isn't `system/init`'s model and
hasn't been reported, the runner SHALL send `served_model`, in the order `modelUsage` lists them, before the
permission-denial `log` warnings and the `result`.

#### Scenario: A model only the result names
- **WHEN** `system/init` names `claude-opus-5-5`, every assistant record is from it, and the result's `modelUsage` has
  `claude-opus-5-5` and `claude-haiku-5-5`
- **THEN** the runner sends `served_model` with `model` `claude-haiku-5-5`, then the `result`

#### Scenario: A model already reported
- **WHEN** an assistant record already led to `served_model` for `claude-sonnet-5-5`, and the result's `modelUsage`
  names it too
- **THEN** no second `served_model` is sent for it
