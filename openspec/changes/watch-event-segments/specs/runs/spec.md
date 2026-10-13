# Spec Delta

## MODIFIED Requirements

### Requirement: Logs read a run's events in order
`logs` SHALL return a run's events in `seq` order, each with the time it was recorded. With `follow`, it SHALL send
each new event as an update as it is recorded, and SHALL stop when the run ends or stops being `running`, saying why.

#### Scenario: Logs of an ended run
- **WHEN** a person asks for the logs of a run with five events
- **THEN** the five events are returned in `seq` order

#### Scenario: Following a run
- **WHEN** a person follows the logs of a running run from another terminal
- **THEN** each event is shown as it is recorded
- **AND** following stops when the run's end is recorded

#### Scenario: Following shows events as they are recorded
- **WHEN** a person follows a running run's logs, with the store's fallback poll interval set to 60 s, and the
  runner sends three events
- **THEN** each event is shown, and the median delay, measured from when the writer's append returned rather than
  from the event's recorded time, is under 0.5 s

#### Scenario: Following an interrupted run
- **WHEN** a person follows the logs of a run that is `interrupted`
- **THEN** the recorded events are shown and following stops at once with the notice `run.interrupted`

## ADDED Requirements

### Requirement: Following subscribes to the store's events
Following SHALL subscribe to the event store's events through the store port, and SHALL have no timer of its own for
finding new events. How the store learns of other writers' events is the store's concern, not following's.

#### Scenario: Nothing is recorded while following
- **WHEN** a person follows a running run's logs, with `SUBSCRIBE_CHECK_SECONDS` set to 60 s, and the run records
  nothing for 2 s
- **THEN** no segment is read in that time

#### Scenario: The store's subscription can only poll
- **WHEN** a person follows a running run's logs and the store's subscription can only poll
- **THEN** the notice `events.subscription-polling` is sent as an update when following starts, and is in the result
- **AND** each event is still sent as it is found by the store's fallback poll

### Requirement: Following notices a run that stops without an end
While following, a run whose `perform` stops without recording an end SHALL be noticed within
`LOGS_LEASE_CHECK_SECONDS`, though nothing was written. Following SHALL then stop with the notice `run.interrupted`.

#### Scenario: Perform dies while the run is followed
- **WHEN** a person follows a running run's logs and its `perform` is killed
- **THEN** following stops within `LOGS_LEASE_CHECK_SECONDS`, plus the time to read the run, with the run `interrupted`
  and the notice `run.interrupted`

### Requirement: Following's limits are named settings
The interval at which following checks a run's lease SHALL be the setting `LOGS_LEASE_CHECK_SECONDS`, with its
default in troupe's one named place for defaults, and overridable. Following SHALL have no poll interval of its own.

#### Scenario: The documentation lists following's defaults
- **WHEN** the runs documentation is checked against the defaults
- **THEN** it lists `LOGS_LEASE_CHECK_SECONDS` with its value, and no `LOGS_FOLLOW_POLL_SECONDS`
