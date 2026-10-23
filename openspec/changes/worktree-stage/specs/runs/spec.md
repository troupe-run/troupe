# Spec Delta

## MODIFIED Requirements

### Requirement: What a run was asked to do is kept
The run's start SHALL record the actor's name, the runner requested, the effect check, the config version it ran
with (the sorted ids of the config stream's heads that the merged config was worked out from), and its workspace. For
a worktree, the workspace SHALL hold the base commit, the worktree's theatre-relative path, whether the theatre was
dirty, and the clone mechanisms used. The direction SHALL be stored as an artifact, and the run's start SHALL
reference it by hash.

#### Scenario: The config a run used
- **WHEN** a run is performed, and the actor's options are changed afterwards
- **THEN** the run's start names the config version from before the change
- **AND** working out config at that version gives the options the run used

#### Scenario: Options are referenced, not inlined
- **WHEN** a run is performed for an actor whose options hold an inline script
- **THEN** no event in the run's stream holds the script itself
- **AND** the run's start references the options through its config version, not as an artifact of their own

#### Scenario: The direction is referenced, not inlined
- **WHEN** a run is performed with a direction
- **THEN** the run's start holds a `sha256:` reference whose artifact is that direction, byte for byte
- **AND** no event in the run's stream holds the direction itself

#### Scenario: A worktree run's workspace
- **WHEN** a worktree run is performed on a clean theatre whose HEAD is commit `c0ffee…`
- **THEN** its start records workspace `worktree`, base `c0ffee…`, the path `.troupe/local/worktrees/<run-id>`, clean,
  and the clone mechanisms used

#### Scenario: A run in place
- **WHEN** a run is performed for an actor whose workspace is `theatre`
- **THEN** its start records workspace `theatre`, with no base, path or clone mechanisms

### Requirement: A run's end records what happened and leaves out what didn't
A run's end SHALL record the outcome's `exitCode`, `transcript` and `stderr` exactly when the runner started, that
is when `ending` isn't `never-started`. It SHALL leave out `error` when the outcome has none, `result` when the runner
sent none, and `recording` when recording didn't fail. It SHALL record `changes` exactly when the run's workspace was
a worktree that was made.

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

#### Scenario: A worktree run whose runner never started
- **WHEN** a worktree run's runner can't be started
- **THEN** its end still records `changes`, with nothing changed, and the worktree is kept until it is discarded

#### Scenario: A run in place has no changes
- **WHEN** a run whose workspace is `theatre` ends
- **THEN** its end has no `changes`

### Requirement: Status reads runs from a projection
`status` SHALL list the most recent runs, newest first, up to a named default limit that a request can lower or
raise. Given a run, it SHALL show that run's summary: its actor, who started it, its runner, its stage, its
workspace, its state, its outcome and error, its changes and their state, its event count, its times, and its
transcript and standard error references.

#### Scenario: Status while a run is going
- **WHEN** a person runs `status` in another terminal while a run is going
- **THEN** the run is listed with state `running` and the number of events recorded so far

#### Scenario: Status after the run
- **WHEN** a person runs `status <run>` after the run ended `failed`
- **THEN** it shows the outcome `failed` and the run's error

#### Scenario: Status of a run with pending changes
- **WHEN** a person runs `status <run>` after a worktree run that changed two files
- **THEN** it shows workspace `worktree`, changes `pending`, the diff's reference, the counts and the worktree's path

## ADDED Requirements

### Requirement: The effect check reads the run's workspace
The effect check's paths SHALL be read in the run's workspace: under the worktree for a worktree run, and under the
theatre for a run in place.

#### Scenario: An expected file in the worktree
- **WHEN** a worktree actor with `expect: ["out/hello.txt"]` writes `out/hello.txt` in its worktree and sends `ok`
- **THEN** the effect check passes and the run `succeeded`, though the theatre has no `out/hello.txt`

### Requirement: A worktree is made only after every check passes
`perform` SHALL make a run's worktree only after the identity, policy, stage and config checks have all passed, and
before the runner starts. A failure to make the worktree SHALL refuse the perform, remove whatever part of the
worktree was made, and record nothing.

#### Scenario: A refused perform makes no worktree
- **WHEN** a perform is refused with `stage.effects-unenforced`
- **THEN** no directory is made under `.troupe/local/worktrees/`

#### Scenario: Making the worktree fails
- **WHEN** git fails while a run's worktree is being made
- **THEN** perform fails with that error, no event is recorded, and no worktree for the run is left registered with
  git or on disk
