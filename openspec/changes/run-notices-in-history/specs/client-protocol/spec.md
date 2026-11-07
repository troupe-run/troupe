# Delta: client-protocol

## ADDED Requirements

### Requirement: A run summary carries its run's recorded notices
A run summary SHALL carry `notices`, each recorded notice of the run with the time it was recorded, in recorded
order, whatever the run's state. It SHALL leave `notices` out when the run recorded none, never sending it empty.

#### Scenario: A run that fell silent
- **WHEN** `status` reports a run that recorded one `run.silent` notice
- **THEN** its summary's `notices` holds one entry, with the time it was recorded and the notice's code, problem
  and fix
- **AND** the summary validates against the client protocol's run schema

#### Scenario: A run with no notices
- **WHEN** `status` reports a run that recorded no notice
- **THEN** its summary has no `notices`

#### Scenario: A summary with an empty notices list
- **WHEN** a run summary has `notices` as an empty list
- **THEN** it doesn't validate against the client protocol's run schema

### Requirement: The logs result holds the run's log
The `logs` result SHALL hold `log`, the run's events and recorded notices in recorded order. Each entry SHALL say
its `kind`: `event` for a run event, with its `seq`, or `run-notice` for a recorded notice, with no `seq`. Both SHALL
name the run and the time the entry was recorded. Following's updates SHALL carry the same entries.

#### Scenario: A log with a notice
- **WHEN** a client reads the `logs` result of a run that recorded a `run.retrying` notice after its `retry` event
- **THEN** its `log` holds an entry of kind `event` for the `retry` event, then one of kind `run-notice` holding
  the notice
- **AND** the result validates against the `logs` result schema

#### Scenario: A recorded notice while following
- **WHEN** a client follows a run that records a notice
- **THEN** it receives an update of kind `run-notice`, distinct from the `notice` updates `logs` itself sends

#### Scenario: A logged notice with a seq
- **WHEN** a `logs` result's entry has kind `run-notice` and a `seq`
- **THEN** it doesn't validate against the `logs` result schema

## MODIFIED Requirements

### Requirement: A run summary carries what its state knows
A run summary SHALL carry `outcome` and `endedAt` exactly when its `state` is `ended`. It SHALL leave out `error`
when the outcome has none, `transcript` and `stderr` when the runner never started, `recording` when recording didn't
fail, `runner.reported` when the runner sent no init, and a worktree workspace's `clones` until its worktree is
made. It SHALL carry `workspace` always, and `changes` exactly when the workspace is a worktree. No field of a summary
SHALL be `null`. A `recording` SHALL name exactly one of `failedAt` and `notice`.

#### Scenario: A running run
- **WHEN** `status` reports a run whose `perform` is still alive
- **THEN** its summary has state `running`, and no `outcome` or `endedAt`

#### Scenario: An ended run
- **WHEN** `status` reports a run whose end is recorded
- **THEN** its summary has state `ended`, an `outcome` and an `endedAt`

#### Scenario: A summary that contradicts its state
- **WHEN** a run summary has state `interrupted` and an `outcome`, or state `ended` and no `endedAt`
- **THEN** it doesn't validate against the client protocol's run schema

#### Scenario: A summary with a null
- **WHEN** a client reads a run summary in which any field is `null`
- **THEN** reading it fails, naming the field

#### Scenario: Changes that contradict the workspace
- **WHEN** a run summary has workspace `theatre` and `changes`, or changes `pending` and no diff reference
- **THEN** it doesn't validate against the client protocol's run schema

#### Scenario: A worktree not made yet
- **WHEN** `status` reports a worktree run whose start is recorded and whose worktree isn't made yet
- **THEN** its summary's workspace has its path, base and whether the theatre was dirty, and no `clones`
- **AND** the summary validates against the client protocol's run schema

#### Scenario: A recording failure on a notice
- **WHEN** `status` reports a run whose end recorded that recording failed at the notice `run.silent`
- **THEN** its summary's `recording` has `notice` `run.silent` and the error, and no `failedAt`

#### Scenario: A recording that names both
- **WHEN** a run summary's `recording` has both `failedAt` and `notice`, or neither
- **THEN** it doesn't validate against the client protocol's run schema
