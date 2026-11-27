## MODIFIED Requirements

### Requirement: Perform shows progress on standard error and the result on standard output
`troupe perform` SHALL write the performance's id at once, then the run id, then each run event and notice as it
happens, to standard error. On success it SHALL write the performance id, the run id and `succeeded` to standard
output. Otherwise standard output SHALL stay empty, and the run's error SHALL be shown on standard error with the run
id.

#### Scenario: Progress while a run is going
- **WHEN** a run is going
- **THEN** standard error shows the performance's id and the actor's name, then the run id, before the first event,
  and a line for each event as it is recorded

#### Scenario: A successful run
- **WHEN** a person performs `tester` and its run ends `succeeded`
- **THEN** standard output is one line naming the performance, the run and `succeeded`

#### Scenario: A failed run
- **WHEN** a run ends `failed`
- **THEN** standard output is empty
- **AND** standard error shows the run id, the problem and the fix

### Requirement: Status and logs commands
`troupe status [<ref>] [--limit <n>]` SHALL show performances and runs, and `troupe logs <ref> [--follow]` SHALL show
a run's log, each as the `status` and `logs` queries return them, where `<ref>` names a run or a performance. Each
line of the list SHALL start with the performance's id. Both SHALL show the store's notices, and the notices the query
derives when it reads a run, on standard error. The notices a run recorded are part of its history, shown as its
summary and log are.

#### Scenario: Logs from another terminal
- **WHEN** a person runs `troupe logs <run> --follow` in another terminal while the run is going
- **THEN** each event appears as it is recorded, and the command exits 0 when the run's end is recorded

#### Scenario: A derived notice stays on standard error
- **WHEN** a person runs `troupe logs <run>` for an `interrupted` run that recorded a `run.silent` notice
- **THEN** the `run.silent` notice is on standard output, among the events, and `run.interrupted` is on standard
  error

#### Scenario: The list starts each line with the performance
- **WHEN** a person has performed `tester` and runs `troupe status`
- **THEN** the line for that perform starts with the performance's id, then names the run and its state as before

#### Scenario: A run's summary names its performance
- **WHEN** a person runs `troupe status <run>`
- **THEN** the summary shows the run's performance and its step
