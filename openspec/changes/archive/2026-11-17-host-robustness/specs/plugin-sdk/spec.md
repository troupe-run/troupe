## ADDED Requirements

### Requirement: The SDK records each lone surrogate a runner replaces
The SDK SHALL give a runner the means to replace each lone surrogate in its engine's text with U+FFFD and to record
it: a `context` event of kind `other`, by `runner`, naming where and how many, sent just before the next event the
run's counter numbers (after `init` at the earliest), one per place. The counter SHALL require, when it is built, the
way to send that event.

#### Scenario: A counter built without a way to record a replacement
- **WHEN** a runner builds the SDK's event counter without saying how to send a `context` event
- **THEN** building it fails at once, naming `send_context`, before any event is numbered

#### Scenario: A replacement recorded before the event that holds it
- **WHEN** a runner numbers a `turn` event whose text holds two lone surrogates, after `init`
- **THEN** a `context` event saying 2 lone surrogates in the turn event's text were replaced with U+FFFD takes the next
  `seq`, and the `turn` event, with U+FFFD in their place, takes the one after it

#### Scenario: Reports for the same place
- **WHEN** a runner reports one replacement in its engine's answer for each of three streamed deltas before its next
  event
- **THEN** one `context` event records all three, before that event
