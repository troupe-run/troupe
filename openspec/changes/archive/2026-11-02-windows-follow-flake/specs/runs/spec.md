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
- **WHEN** a person follows a running run's logs from another process, with the store's fallback poll and check
  intervals and following's run check all set to 60 s, and the run's process records each event only once following
  has shown the event before it, five times, and then, while no delay so far is under 0.5 s, once more at a time for
  up to a 60 s allowance for a slow stretch
- **THEN** each event is shown before the next one is recorded, so following woke on that event's own write rather
  than on a later event or a timer
- **AND** the fastest of the delays, measured from when the writer's append returned rather than from the event's
  recorded time, is under 0.5 s, and the median of the first five is within 0.5 s plus an allowance for a loaded
  machine

#### Scenario: Following an interrupted run
- **WHEN** a person follows the logs of a run that is `interrupted`
- **THEN** the recorded events are shown and following stops at once with the notice `run.interrupted`
