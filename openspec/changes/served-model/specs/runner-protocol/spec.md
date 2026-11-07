## MODIFIED Requirements

### Requirement: Run events are notifications with a sequence number
The runner SHALL report the run as `run/event` notifications. Each event SHALL carry the run id, a `seq` that
starts at 0 and increases by one with each event, and a `type`. The event types SHALL be `init`, `turn`,
`tool_call`, `tool_result`, `retry`, `log`, `served_model` and `result`.

#### Scenario: Events are numbered without gaps
- **WHEN** a runner sends events for a run
- **THEN** their `seq` values are 0, 1, 2 and so on, without gaps or repeats

#### Scenario: Gap in the sequence
- **WHEN** the host receives an event whose `seq` is not one more than the previous event's
- **THEN** the host treats it as a protocol violation

## ADDED Requirements

### Requirement: A model other than init's is reported as it answers
A runner SHALL send a `served_model` event, whose `model` is the name the engine or service gave, the first time a
model answers part of the run when that model isn't the one `init` named, before any event reporting that answer.
It SHALL NOT name `init`'s model, or a model already reported in the run. With no model on `init`, every model that
answers is reported once.

#### Scenario: A service answers as a dated snapshot
- **WHEN** `init`'s engine names the model `gpt-6-luna` and the first response says it came from
  `gpt-6-luna-2026-03-05`
- **THEN** the runner sends `served_model` with `model` `gpt-6-luna-2026-03-05` before that response's `turn` or
  `result`

#### Scenario: The same model answers again
- **WHEN** a later response in the same run also came from `gpt-6-luna-2026-03-05`
- **THEN** no second `served_model` is sent

#### Scenario: The model asked for answers
- **WHEN** every response came from the model `init` named
- **THEN** the run has no `served_model` event

#### Scenario: Init named no model
- **WHEN** `init` has no `engine.model` and a response names the model `m-1`
- **THEN** the runner sends `served_model` with `model` `m-1`

### Requirement: A served model's name has a model's shape
A `served_model` event's `model` SHALL be 1 to 256 characters with no control character, the shape of `run/start`'s
`runtime.model`. When the engine or service names a model outside that shape, the runner SHALL send a `log` warning
that says so, with the name cut to fit, and no `served_model` for it.

#### Scenario: A name with a control character
- **WHEN** a response names the model `bad\nname`
- **THEN** the runner sends a `log` at `warning` saying the service named a model troupe can't record, and no
  `served_model`

#### Scenario: An event that breaks the shape
- **WHEN** a runner sends `served_model` with a `model` of 257 characters, or of none
- **THEN** it does not validate against the contract's schema, and the host treats it as a protocol violation
