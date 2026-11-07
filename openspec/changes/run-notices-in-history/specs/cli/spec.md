# Delta: cli

## ADDED Requirements

### Requirement: Status and logs show a run's recorded notices
`troupe status <run>` SHALL list each notice the run recorded, with the time it was recorded, its code and its
problem. `troupe status` SHALL add a run's notice count to its line when it recorded any. `troupe logs <run>` SHALL
show each recorded notice on standard output, on its own line among the run's events in recorded order, marked as a
notice. A run that recorded no notice SHALL show no notice line.

#### Scenario: Status of a run that fell silent
- **WHEN** a person runs `troupe status <run>` for a run that recorded a `run.silent` notice
- **THEN** the output lists the notice with its time, the code `run.silent` and its problem

#### Scenario: The list of runs
- **WHEN** a person runs `troupe status` and one listed run recorded two notices
- **THEN** that run's line says it has 2 notices, and the other runs' lines say nothing about notices

#### Scenario: Logs of a run that retried
- **WHEN** a person runs `troupe logs <run>` for a run that sent `init`, a `retry` event and a result
- **THEN** standard output shows the `init` line, the `retry` line, a notice line for `run.retrying`, then the result
  line

#### Scenario: Following a run that falls silent
- **WHEN** a person runs `troupe logs <run> --follow` while the run falls silent
- **THEN** the `run.silent` notice line appears on standard output once it is recorded, among the event lines

#### Scenario: A run with no notices
- **WHEN** a person runs `troupe status <run>` for a run that recorded no notice
- **THEN** the output has no notice line

## MODIFIED Requirements

### Requirement: Status and logs commands
`troupe status [<run>] [--limit <n>]` SHALL show runs, and `troupe logs <run> [--follow]` SHALL show a run's log,
each as the `status` and `logs` queries return them. Both SHALL show the store's notices, and the notices the query
derives when it reads a run, on standard error. The notices a run recorded are part of its history, shown as its
summary and log are.

#### Scenario: Logs from another terminal
- **WHEN** a person runs `troupe logs <run> --follow` in another terminal while the run is going
- **THEN** each event appears as it is recorded, and the command exits 0 when the run's end is recorded

#### Scenario: A derived notice stays on standard error
- **WHEN** a person runs `troupe logs <run>` for an `interrupted` run that recorded a `run.silent` notice
- **THEN** the `run.silent` notice is on standard output, among the events, and `run.interrupted` is on standard
  error
