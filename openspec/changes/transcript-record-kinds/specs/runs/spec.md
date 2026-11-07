# Spec Delta

## MODIFIED Requirements

### Requirement: A run's end records what happened and leaves out what didn't
A run's end SHALL record the outcome's `exitCode`, `transcript`, `transcriptFormat` and `stderr` exactly when the
runner started, that is when `ending` isn't `never-started`. It SHALL leave out `error` when the outcome has none,
`result` when the runner sent none, and `recording` when recording didn't fail. It SHALL record `changes` exactly when
the run's workspace was a worktree that was made.

#### Scenario: A run whose runner never started
- **WHEN** a run's runner can't be started
- **THEN** its end records outcome `could-not-start` and ending `never-started`, with an `error` and no `exitCode`,
  `transcript`, `transcriptFormat`, `stderr`, `result` or `recording`

#### Scenario: A run that succeeded
- **WHEN** a run's runner sends an `ok` result and exits with code 0
- **THEN** its end records `exitCode` 0, the `transcript`, its `transcriptFormat`, `stderr` and `result`, and no
  `error` or `recording`

#### Scenario: An end that contradicts its ending
- **WHEN** a run's end payload has ending `exited` and no `exitCode`, or ending `never-started` and a `transcript`
- **THEN** it doesn't validate against the run's end schema

#### Scenario: A worktree run whose runner never started
- **WHEN** a worktree run's runner can't be started
- **THEN** its end still records `changes`, with nothing changed, and the worktree is kept until it is discarded

#### Scenario: A run in place has no changes
- **WHEN** a run whose workspace is `theatre` ends
- **THEN** its end has no `changes`

## ADDED Requirements

### Requirement: A run's end says which form its transcript is
`transcriptFormat` SHALL be `kinds` when the runner accepted `transcript-kinds`, and `native` otherwise. A run's end
with a `transcript` and no `transcriptFormat`, or the reverse, SHALL NOT validate.

#### Scenario: A run that used kinds
- **WHEN** a run's runner accepted `transcript-kinds` and the run ends
- **THEN** its end records `transcriptFormat` `kinds`

#### Scenario: A Claude Code run
- **WHEN** a Claude Code run ends
- **THEN** its end records `transcriptFormat` `native`

#### Scenario: A transcript without its format
- **WHEN** a run's end payload has ending `exited`, a `transcript` and no `transcriptFormat`
- **THEN** it doesn't validate against the run's end schema

#### Scenario: A format without a transcript
- **WHEN** a run's end payload has ending `never-started` and a `transcriptFormat`
- **THEN** it doesn't validate against the run's end schema
