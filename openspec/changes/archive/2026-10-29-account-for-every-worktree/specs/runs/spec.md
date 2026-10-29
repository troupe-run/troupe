# Spec Delta

## ADDED Requirements

### Requirement: A failure before the runner starts ends the run
When anything fails after a run's start is recorded and before its runner starts, such as making its worktree or
reading the repository's shared state, the run's end SHALL be recorded with outcome `could-not-start`, the failure as
its error, and the runner's ending `never-started`. `perform` SHALL then fail with that error, as it did before the
start came first.

#### Scenario: Reading the shared state fails
- **WHEN** a worktree run's worktree is made, and git then fails while troupe reads the repository's shared state
- **THEN** perform fails with git's error
- **AND** the run's stream holds its start, its worktree's clone mechanisms and its end, with outcome
  `could-not-start` and git's error, and no runner was started

#### Scenario: Ending the run fails too
- **WHEN** making a run's worktree fails, and recording the run's end then fails
- **THEN** perform fails with `run.recording-failed`, naming the run, the error that stopped the worktree, and the
  error recording its end
- **AND** `status` shows the run as `interrupted`, and it can be discarded

## RENAMED Requirements

- FROM: `### Requirement: Init is recorded first`
- TO: `### Requirement: A run's start is recorded before its runner starts`

- FROM: `### Requirement: A run's start leaves out a runner that never reported`
- TO: `### Requirement: A run's summary leaves out a runner that never reported`

## MODIFIED Requirements

### Requirement: A run's start is recorded before its runner starts
The run's start SHALL be recorded before its runner starts, and before its workspace is made, once every check that
can refuse the run has passed. The runner's `init` event SHALL be the first run event recorded, and the run's
reported runner name and version SHALL be read from it. A run that ends without `init` SHALL have its start followed
by its end.

#### Scenario: The runner's name and version
- **WHEN** a runner's `init` names runner `scripted`, version `0.1.0`
- **THEN** the run's first reported event is that `init`, and the run's summary reports runner `scripted`, version
  `0.1.0`

#### Scenario: A runner that never starts
- **WHEN** a person performs an actor whose runner can't be started
- **THEN** the run's stream holds its start and its end, with outcome `could-not-start`

#### Scenario: The start comes before the runner
- **WHEN** a person performs an actor, and the run is read while its runner is starting, before it sends `init`
- **THEN** the run's start is recorded, and `status` shows the run as `running`

#### Scenario: Killed before init
- **WHEN** a run's `perform` is killed after its runner started and before the runner sent `init`
- **THEN** `status` shows the run as `interrupted`, with the notice `run.interrupted`

### Requirement: A run's summary leaves out a runner that never reported
A run's summary SHALL report the runner's name and version from its `init` event when the runner sent one, and SHALL
leave the reported runner out when it never did. The run's start SHALL NOT record the reported runner.

#### Scenario: A runner that never sent init
- **WHEN** a run ends before its runner sends an init
- **THEN** its start has no `runner_reported`, and the run's summary has no `runner.reported`

#### Scenario: A start recorded by an older troupe
- **WHEN** a run's start holds `runner_reported`, as troupe recorded it before the start came before the runner
- **THEN** the run reads back, and its summary reports that runner

### Requirement: What a run was asked to do is kept
The run's start SHALL record the actor's name, the runner requested, the effect check, the config version it ran
with (the sorted ids of the config stream's heads that the merged config was worked out from), and its workspace. For
a worktree, the workspace SHALL hold the base commit, the worktree's theatre-relative path and whether the theatre was
dirty. The direction SHALL be stored as an artifact before the start is recorded, and the run's start SHALL
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
- **THEN** its start records workspace `worktree`, base `c0ffee…`, the path `.troupe/local/worktrees/<run-id>` and
  clean, and no clone mechanisms

#### Scenario: A run in place
- **WHEN** a run is performed for an actor whose workspace is `theatre`
- **THEN** its start records workspace `theatre`, with no base, path or clone mechanisms

#### Scenario: The direction can't be stored
- **WHEN** storing a run's direction as an artifact fails
- **THEN** `perform` fails with the artifact store's error
- **AND** nothing is recorded, and no worktree is made

### Requirement: A worktree is made only after every check passes
`perform` SHALL make a run's worktree only after the identity, policy, stage and config checks have all passed and
the run's start is recorded, and before the runner starts. A failure to make the worktree SHALL fail the perform,
remove whatever part of the worktree was made, and end the run.

#### Scenario: A refused perform makes no worktree
- **WHEN** a perform is refused with `stage.effects-unenforced`
- **THEN** no directory is made under `.troupe/local/worktrees/`, and nothing is recorded

#### Scenario: Making the worktree fails
- **WHEN** git fails while a run's worktree is being made
- **THEN** perform fails with that error, and no worktree for the run is left registered with git or on disk
- **AND** the run's stream holds its start and its end, with outcome `could-not-start` and that error
