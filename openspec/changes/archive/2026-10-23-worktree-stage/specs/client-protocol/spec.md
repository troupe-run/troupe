# Spec Delta

## MODIFIED Requirements

### Requirement: A run summary carries what its state knows
A run summary SHALL carry `outcome` and `endedAt` exactly when its `state` is `ended`. It SHALL leave out `error`
when the outcome has none, `transcript` and `stderr` when the runner never started, `recording` when recording didn't
fail, and `runner.reported` when the runner sent no init. It SHALL carry `workspace` always, and `changes` exactly
when the workspace is a worktree. No field of a summary SHALL be `null`.

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

## ADDED Requirements

### Requirement: Diff, accept and discard are protocol calls
`diff` SHALL be a query, and `accept` and `discard` commands, each defined in the client protocol with a request and
result schema. Each request SHALL name a run, and `accept` and `discard` requests SHALL take an optional `reason` and
`rehearse`. No request SHALL name a path, a diff or a workspace.

#### Scenario: A request that names a diff
- **WHEN** an `accept` request holds a `diff` field
- **THEN** it is refused with `client.invalid-request`, naming the field

#### Scenario: Results validate
- **WHEN** a `diff`, `accept` or `discard` call succeeds or is refused
- **THEN** its result or error validates against the protocol's schema for that call
