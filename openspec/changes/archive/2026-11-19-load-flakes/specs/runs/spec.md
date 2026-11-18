## MODIFIED Requirements

### Requirement: Following subscribes to the store's events
Following SHALL subscribe to the event store's events through the store port, and SHALL have no timer of its own for
finding new events. How the store learns of other writers' events is the store's concern, not following's.

#### Scenario: Nothing is recorded while following
- **WHEN** a person follows a running run's logs, with `SUBSCRIBE_CHECK_SECONDS` set to 60 s, and the run records
  nothing for 2 s
- **THEN** a segment is read in that time only after the store's watch reports a change, once for each report, which
  the OS may make late for a change made earlier, and never on a timer

#### Scenario: The store's subscription can only poll
- **WHEN** a person follows a running run's logs and the store's subscription can only poll
- **THEN** the notice `events.subscription-polling` is sent as an update when following starts, and is in the result
- **AND** each event is still sent as it is found by the store's fallback poll
