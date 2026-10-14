# Spec Delta

## MODIFIED Requirements

### Requirement: A subscription that can only poll says so
When a store can't learn of other writers' events as they're recorded, its subscription SHALL find them by looking
every `SUBSCRIBE_POLL_SECONDS` instead, and while it does, the store's notices SHALL include
`events.subscription-polling`, naming the reason, the fix and, where there is one, the path. It SHALL never poll
silently.

#### Scenario: The text store's directory can't be watched
- **WHEN** a process subscribes to a text store and the platform refuses to watch its events directory
- **THEN** the store's notices include `events.subscription-polling`, with the reason `watch-refused`, the directory
  and the platform's reason
- **AND** before each look, the subscription waits once, for `SUBSCRIBE_POLL_SECONDS`
- **AND** when another process records an event, five times, each event reaches the subscriber, delivered no later
  than the first look the subscription started after the writer's append returned
- **AND** the median delay of the five, measured from when the writer's append returned, is within
  `SUBSCRIBE_POLL_SECONDS` plus an allowance for a loaded machine

#### Scenario: The notice lasts as long as the polling
- **WHEN** the store's notices are read twice while its subscription is polling
- **THEN** both include `events.subscription-polling`

### Requirement: A subscription that finds it missed an event says so
Every `SUBSCRIBE_CHECK_SECONDS` while it has subscribers, the store SHALL look for other writers' events itself. If it
finds one that its notification didn't deliver in that interval, it SHALL deliver it, change to polling, and announce
`events.subscription-polling`, saying an event was missed.

#### Scenario: A text store whose watch never reports
- **WHEN** a process subscribes to a text store through a watch that is set up but never reports, and another process
  records an event
- **THEN** the event reaches the subscriber within `SUBSCRIBE_CHECK_SECONDS`, plus an allowance for the time to read
  it on a loaded machine
- **AND** the store's notices include `events.subscription-polling`, with the reason `watch-missed-write`
- **AND** before each look it then makes, the subscription waits once, for `SUBSCRIBE_POLL_SECONDS`
- **AND** when another process then records an event, five times, each event reaches the subscriber, delivered no
  later than the first look the subscription started after the writer's append returned
- **AND** the median delay of the five, measured from when the writer's append returned, is within
  `SUBSCRIBE_POLL_SECONDS` plus an allowance for a loaded machine
