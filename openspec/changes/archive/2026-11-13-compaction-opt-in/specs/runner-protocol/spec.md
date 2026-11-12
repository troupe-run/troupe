## ADDED Requirements

### Requirement: Run start says whether the run may compact
The `run/start` request SHALL carry `onContextFull`, `fail` or `compact`: the value troupe resolved from the actor and
policy. A runner told `fail` SHALL NOT compact or drop content of the conversation, and SHALL let its engine do
neither. A runner told `compact` MAY, and SHALL report each time with a `context` event.

#### Scenario: Run start without it
- **WHEN** a `run/start` has no `onContextFull`
- **THEN** it does not validate against the contract's schema

#### Scenario: A value off the list
- **WHEN** a `run/start` has `onContextFull` `summarise`
- **THEN** it does not validate against the contract's schema

#### Scenario: A runner told to fail
- **WHEN** a run with `onContextFull` `fail` fills its engine's context
- **THEN** the runner sends no `context` event, and the run ends with an `error` result whose `reason` is
  `context-length`

#### Scenario: A runner with no engine
- **WHEN** the scripted runner receives a `run/start` with `onContextFull` `compact`
- **THEN** it accepts it and plays its script unchanged

### Requirement: A compaction that can't make room ends the run with context-length
When a run told `compact` can't reduce its conversation enough to send its next request, the runner SHALL end the
run with an `error` result whose `reason` is `context-length` and whose message says compaction was on.

#### Scenario: Nothing left to remove
- **WHEN** a run told `compact` has already compacted everything it may, and its next request still doesn't fit
- **THEN** the run ends with `error` and `reason` `context-length`, and the message says compaction found nothing
  more to remove
