# Spec Delta

## MODIFIED Requirements

### Requirement: A run summary carries what its state knows
A run summary SHALL carry `outcome` and `endedAt` exactly when its `state` is `ended`. It SHALL leave out `error`
when the outcome has none, `transcript` and `stderr` when the runner never started, `recording` when recording didn't
fail, `runner.reported` when the runner sent no init, and a worktree workspace's `clones` until its worktree is
made. It SHALL carry `workspace` always, and `changes` exactly when the workspace is a worktree. No field of a summary
SHALL be `null`.

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
