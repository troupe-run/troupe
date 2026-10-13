# Spec Delta

## ADDED Requirements

### Requirement: A subscription delivers other writers' events as they're recorded
A subscription to the event store SHALL deliver every new event, whoever wrote it (this process, another process, or
git bringing in segments), within a bound, without the subscriber or the store looking for it on a timer. Subscribers
SHALL see only the store port's subscription, never how a store learns of writes.

#### Scenario: Another process records events
- **WHEN** a process subscribes to the store, with `SUBSCRIBE_POLL_SECONDS` and `SUBSCRIBE_CHECK_SECONDS` set to 60 s,
  and another process records an event, five times
- **THEN** each event reaches the subscriber, and the median delay, measured from when the writer's append returned,
  is under 0.25 s

#### Scenario: The same guarantee through the port
- **WHEN** the installed store is loaded by name through the port with its defaults, and another process records an
  event while a subscriber waits, five times
- **THEN** each event reaches the subscriber, and the median delay, measured from when the writer's call to record it
  returned, is under 0.25 s

#### Scenario: The text store's first write creates its events directory
- **WHEN** a process subscribes to a text store that has no events yet, and another process records the first event
- **THEN** the event reaches the subscriber, though the events directory didn't exist when it subscribed

#### Scenario: The text store does no work while nothing is recorded
- **WHEN** a process subscribes to a text store, with `SUBSCRIBE_CHECK_SECONDS` set to 60 s, and nothing is recorded
  for 2 s
- **THEN** the store reads no segment in that time

### Requirement: A subscription that can only poll says so
When a store can't learn of other writers' events as they're recorded, its subscription SHALL find them by looking
every `SUBSCRIBE_POLL_SECONDS` instead, and while it does, the store's notices SHALL include
`events.subscription-polling`, naming the reason, the fix and, where there is one, the path. It SHALL never poll
silently.

#### Scenario: The text store's directory can't be watched
- **WHEN** a process subscribes to a text store and the platform refuses to watch its events directory
- **THEN** the store's notices include `events.subscription-polling`, with the reason `watch-refused`, the directory
  and the platform's reason
- **AND** another process's event still reaches the subscriber within `SUBSCRIBE_POLL_SECONDS`, plus the time to read
  it

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
- **THEN** the event reaches the subscriber within `SUBSCRIBE_CHECK_SECONDS`, plus the time to read it
- **AND** the store's notices include `events.subscription-polling`, with the reason `watch-missed-write`
- **AND** later events reach the subscriber within `SUBSCRIBE_POLL_SECONDS`

## MODIFIED Requirements

### Requirement: Store limits are named settings
Every limit the store uses (lock waits, the subscription's check interval and the interval of its fallback poll)
SHALL have its default in troupe's one named place for defaults, and SHALL be overridable.

#### Scenario: The documentation lists the store's defaults
- **WHEN** the store's documentation is checked against the defaults
- **THEN** it lists exactly the defaults the store uses, with their values
