## ADDED Requirements

### Requirement: A context event is recorded and shown like every run event
troupe SHALL record a runner's `context` event as it records every run event, with its lineage, in `seq` order. `logs`
SHALL show it with its kind, who lost the content and each amount it carries. It SHALL NOT change the run's outcome.

#### Scenario: A run whose engine compacted
- **WHEN** a runner sends `init`, a `context` event with kind `compacted`, by `engine` and `tokensBefore` 41000, and
  then an `ok` result, and the run exits cleanly with a passing effect check
- **THEN** the run's events hold a `Run.Reported` carrying that `context` event unchanged, with lineage
- **AND** the run's outcome is `succeeded`

#### Scenario: Logs show the loss
- **WHEN** a person reads the logs of that run
- **THEN** the `context` event's line names `compacted`, `engine` and 41000 tokens before

#### Scenario: An oversized context event
- **WHEN** a runner sends a `context` event larger than the run's maximum event size
- **THEN** troupe records an `oversized` event whose `originalType` is `context`, and keeps the original in the
  artifact store
