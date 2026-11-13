## MODIFIED Requirements

### Requirement: A run's state is derived, never recorded as running
A run SHALL be `ended` when its end is recorded. Otherwise it SHALL be `running` while the `perform` that runs it is
alive in this clone, `interrupted` when that `perform` has gone without recording an end, and `unfinished-elsewhere`
when it was started in another clone. Nothing SHALL be recorded on behalf of an interrupted run.

#### Scenario: Perform is killed
- **WHEN** the process running `perform` is killed while its run is going
- **THEN** `status` shows the run as `interrupted`, with the notice `run.interrupted`
- **AND** no end is recorded for it

#### Scenario: Perform has ended while the OS still holds its lease
- **WHEN** the process running `perform` has ended without recording an end, and the run's lease still reads as held
  because the OS hasn't yet released the ended process's lock
- **AND** `status` runs in the same pid namespace as that `perform` did
- **THEN** `status` shows the run as `interrupted`, with the notice `run.interrupted`

#### Scenario: A held lease from another pid namespace
- **WHEN** a run's lease is held, and the `perform` holding it runs in another pid namespace than `status`, such as
  a container sharing the theatre, so its process id names nothing where `status` runs
- **THEN** `status` shows the run as `running`

#### Scenario: A run from another clone
- **WHEN** a run's start and events arrive by a merge, with no end, from a clone where it was started
- **THEN** `status` shows the run as `unfinished-elsewhere`, with the notice `run.unfinished-elsewhere`
