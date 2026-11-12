## ADDED Requirements

### Requirement: Every prediction stops at the context length
Every prediction the runner asks LM Studio for SHALL set `contextOverflowPolicy` to `stopAtLimit`, whatever the
server's or the model's own setting. The other policies (`truncateMiddle`, `rollingWindow`) drop content while the
run carries on, and LM Studio doesn't tell the client when they do, so the run couldn't report it. A prediction that
reaches the context length then ends the run with `context-length`.

#### Scenario: A prediction's config
- **WHEN** a run asks LM Studio for a prediction, with or without a `temperature`
- **THEN** the prediction's config holds `contextOverflowPolicy` `stopAtLimit`

#### Scenario: A full context
- **WHEN** a round stops with `contextLengthReached`
- **THEN** the run ends with an `error` result whose `reason` is `context-length`

### Requirement: A run told compact says the runner doesn't compact
When `run/start`'s `onContextFull` is `compact`, the runner SHALL send a `log` warning just after `init`, saying it
doesn't compact a conversation and that a full context ends the run with `context-length`. It SHALL NOT compact or
send a `context` event.

#### Scenario: A run told compact
- **WHEN** a run starts with `onContextFull` `compact`
- **THEN** the event after `init` is a `log` warning naming `onContextFull` and `context-length`, and the run sends no
  `context` event

#### Scenario: A run told fail
- **WHEN** a run starts with `onContextFull` `fail`
- **THEN** no event names `onContextFull`
