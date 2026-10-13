# Spec Delta

## ADDED Requirements

### Requirement: A run's start leaves out a runner that never reported
A run's start SHALL record the runner's reported name and version when the runner sent an init, and SHALL leave the
reported runner out when it never did.

#### Scenario: A runner that never sent init
- **WHEN** a run ends before its runner sends an init
- **THEN** its start has no `runner_reported`, and the run's summary has no `runner.reported`

### Requirement: A run's end records what happened and leaves out what didn't
A run's end SHALL record the outcome's `exitCode`, `transcript` and `stderr` exactly when the runner started, that
is when `ending` isn't `never-started`. It SHALL leave out `error` when the outcome has none, `result` when the runner
sent none, and `recording` when recording didn't fail.

#### Scenario: A run whose runner never started
- **WHEN** a run's runner can't be started
- **THEN** its end records outcome `could-not-start` and ending `never-started`, with an `error` and no `exitCode`,
  `transcript`, `stderr`, `result` or `recording`

#### Scenario: A run that succeeded
- **WHEN** a run's runner sends an `ok` result and exits with code 0
- **THEN** its end records `exitCode` 0, the `transcript`, `stderr` and `result`, and no `error` or `recording`

#### Scenario: An end that contradicts its ending
- **WHEN** a run's end payload has ending `exited` and no `exitCode`, or ending `never-started` and a `transcript`
- **THEN** it doesn't validate against the run's end schema

### Requirement: A recording failure leaves out what it can't name
`run.recording-failed` SHALL leave out `failedAt` when only the run's end failed to record, `endError` when the end
was recorded, and `transcript` when the runner never started.

#### Scenario: Only the end fails to record
- **WHEN** every run event is recorded and recording the run's end fails
- **THEN** `perform` fails with `run.recording-failed`, whose details have `endError` and no `failedAt`

#### Scenario: A run event fails to record and the end is recorded
- **WHEN** recording the run event with `seq` 2 fails and the run's end is recorded
- **THEN** the details have `failedAt` 2 and no `endError`
