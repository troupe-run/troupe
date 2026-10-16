# Spec Delta

## MODIFIED Requirements

### Requirement: A subscription delivers other writers' events as they're recorded
A subscription to the event store SHALL deliver every new event, whoever wrote it (this process, another process, or
git bringing in segments), within a bound, without the subscriber or the store looking for it on a timer. Subscribers
SHALL see only the store port's subscription, never how a store learns of writes.

#### Scenario: Another process records events
- **WHEN** a process subscribes to the store, with `SUBSCRIBE_POLL_SECONDS` and `SUBSCRIBE_CHECK_SECONDS` set to 60 s,
  and another process records an event, five times
- **THEN** each event reaches the subscriber, the fastest of the five delays, measured from when the writer's append
  returned, is under 0.25 s, and their median is within 0.25 s plus an allowance for a loaded machine

#### Scenario: The same guarantee through the port
- **WHEN** the installed store is loaded by name through the port with its defaults, and another process records an
  event while a subscriber waits, five times
- **THEN** each event reaches the subscriber, the fastest of the five delays, measured from when the writer's call to
  record it returned, is under 0.25 s, and their median is within 0.25 s plus an allowance for a loaded machine

#### Scenario: The text store's first write creates its events directory
- **WHEN** a process subscribes to a text store that has no events yet, and another process records the first event
- **THEN** the event reaches the subscriber, though the events directory didn't exist when it subscribed

#### Scenario: The text store does no work while nothing is recorded
- **WHEN** a process subscribes to a text store, with `SUBSCRIBE_CHECK_SECONDS` set to 60 s, and nothing is recorded
  for 2 s
- **THEN** the store reads no segment in that time
