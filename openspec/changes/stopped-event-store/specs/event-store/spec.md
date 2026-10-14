# Spec Delta

## ADDED Requirements

### Requirement: A stopped subscription leaves the store alone
When stopping a subscription returns, the store SHALL have finished all work done for that subscription. It SHALL
not read the store, write any file under the theatre, or deliver to any listener for that subscription afterwards.
Anything it watched the file system with SHALL be released. This holds whatever the subscription was doing when it
was stopped, including if it hadn't started yet.

#### Scenario: A subscription stopped before its first delivery
- **WHEN** a process subscribes to a text store whose order needs rebuilding, and stops the subscription before the
  subscription has delivered anything
- **THEN** when the stop returns, the store's subscription work has ended
- **AND** no file under the theatre is created, changed or removed in the second after the stop returned

#### Scenario: A subscription stopped while it delivers
- **WHEN** a subscription is delivering, and the subscriber stops it before that delivery is finished
- **THEN** the stop returns only after the delivery has finished, and the store's subscription work has then ended

#### Scenario: The library's subscription case cleans up
- **WHEN** the event-sourcing library's subscription case runs against the text store, and its temporary theatre is
  deleted as soon as the case ends
- **THEN** the deletion succeeds, and no exception is raised in any other thread

### Requirement: Stopping a subscription never waits silently or indefinitely
Waiting for a subscription's work to end SHALL be bounded by `SUBSCRIBE_STOP_TIMEOUT_SECONDS`. If the wait lasts the
store's lock-announce interval, it SHALL be announced. If it reaches the bound, stopping SHALL fail with
`events.subscription-not-stopped`, naming the events directory, how long it waited and the fix. It SHALL never
return as though the subscription had stopped.

#### Scenario: Subscription work that doesn't end
- **WHEN** a subscription's work doesn't end once it is stopped, with `SUBSCRIBE_STOP_TIMEOUT_SECONDS` set to 0.5 s
- **THEN** the wait is announced once, naming the events directory
- **AND** stopping fails with `events.subscription-not-stopped` after between 0.5 s and 0.5 s plus an allowance for a
  loaded machine
- **AND** the error validates against the protocol's error schema

## MODIFIED Requirements

### Requirement: Store limits are named settings
Every limit the store uses (lock waits, the subscription's check interval, the interval of its fallback poll, and how
long stopping a subscription waits for its work to end) SHALL have its default in troupe's one named place for
defaults, and SHALL be overridable.

#### Scenario: The documentation lists the store's defaults
- **WHEN** the store's documentation is checked against the defaults
- **THEN** it lists exactly the defaults the store uses, with their values
