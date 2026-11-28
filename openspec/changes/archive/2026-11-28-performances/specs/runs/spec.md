## MODIFIED Requirements

### Requirement: Perform runs one actor and records the run
`perform` SHALL run one actor through its runner on its stage, and record the run in the event store as the one step
of a new performance (spec: performances). The run id SHALL be a new UUID, in canonical lowercase form, minted by
`perform`.

#### Scenario: A successful run is recorded
- **WHEN** a person performs an actor whose scripted runner sends `init`, two `turn`s and an `ok` result, and whose
  effect check passes
- **THEN** the run's stream holds, in order, the run's start, one event for each of the four run events in `seq`
  order, and the run's end with outcome `succeeded`
- **AND** the performance's stream holds its start and its end, with outcome `completed`

### Requirement: Status reads runs from a projection
`status` SHALL list the most recent performances, newest first, one line each, up to a named default limit that a
request can lower or raise. Given a run, it SHALL show that run's summary: its actor, who started it, its runner, its
stage, its workspace, its state, its outcome and error, its changes and their state, its event count, its recorded
notices, its times, and its transcript and standard error references.

#### Scenario: Status while a run is going
- **WHEN** a person runs `status` in another terminal while a run is going
- **THEN** the run is listed with its performance, state `running` and the number of events recorded so far

#### Scenario: Status after the run
- **WHEN** a person runs `status <run>` after the run ended `failed`
- **THEN** it shows the outcome `failed` and the run's error

#### Scenario: Status of a run with pending changes
- **WHEN** a person runs `status <run>` after a worktree run that changed two files
- **THEN** it shows workspace `worktree`, changes `pending`, the diff's reference, the counts and the worktree's path

#### Scenario: Status of a run that raised notices
- **WHEN** a person runs `status <run>` after an unattended run that fell silent once and retried once
- **THEN** its summary holds the `run.silent` and `run.retrying` notices, in the order they were raised, each with
  the time it was recorded

#### Scenario: Status of an interrupted run that raised a notice
- **WHEN** a person runs `status <run>` for an `interrupted` run that recorded a `run.silent` notice before its
  `perform` was killed
- **THEN** its summary holds the `run.silent` notice

#### Scenario: The limit counts performances
- **WHEN** three actors have been performed and a person runs `status` with a limit of 2
- **THEN** the two most recent performances are listed

### Requirement: Runs are named by id or unique prefix
A query SHALL accept a run's full id, or a prefix of at least 8 hex digits that matches exactly one run or
performance, and a performance's id as the performances spec says. A prefix that matches none SHALL be refused with
`run.not-found`, and one that matches several with `run.ambiguous-id`, listing them.

#### Scenario: An ambiguous prefix
- **WHEN** two runs' ids both start with `1a2b3c4d` and a person asks for `status 1a2b3c4d`
- **THEN** it is refused with `run.ambiguous-id`, listing both runs

#### Scenario: A performance's id
- **WHEN** a person asks for `logs <performance>` for an actor's performance
- **THEN** it returns the log of the performance's run
