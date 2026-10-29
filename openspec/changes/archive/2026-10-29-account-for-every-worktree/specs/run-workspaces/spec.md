# Spec Delta

## ADDED Requirements

### Requirement: Every worktree troupe makes is named by an event
A worktree run's start, naming the worktree's path, SHALL be recorded before any part of the worktree is made. So a
run's worktree, whole or partly made, SHALL always belong to a run that `status` shows and `discard` can name, however
`perform` stops.

#### Scenario: Killed while the worktree is being made
- **WHEN** a worktree run's `perform` is killed while git is making its worktree
- **THEN** `status` shows the run as `interrupted`, with its changes `uncaptured` and the worktree's path
- **AND** discarding the run removes whatever part of the worktree was made, and its registration with git

#### Scenario: Killed before the runner sent init
- **WHEN** a worktree run's `perform` is killed after its worktree is made and before its runner sends `init`
- **THEN** `status` shows the run as `interrupted`, with its changes `uncaptured` and the worktree's path
- **AND** discarding the run removes the worktree

#### Scenario: Killed before the worktree was begun
- **WHEN** a worktree run's `perform` is killed after its start is recorded and before git begins making its worktree
- **THEN** `status` shows the run as `interrupted`, and discarding it succeeds and records the discard

## MODIFIED Requirements

### Requirement: Files that match HEAD are cloned copy-on-write
When the worktree is made, each file that is the same in the theatre and in HEAD SHALL be cloned from the theatre
through the platform seam, copy-on-write where the filesystem supports it. Each other file SHALL be checked out from
git. Once the worktree is made, and before the runner starts, the run SHALL record the clone mechanisms that were
used, and its summary's workspace SHALL show them.

#### Scenario: On APFS
- **WHEN** a worktree is made on macOS on an APFS volume
- **THEN** the files that match HEAD are cloned with `clonefile`, and the run records that mechanism

#### Scenario: On a filesystem without clones
- **WHEN** a worktree is made on a filesystem that can't clone, such as ext4
- **THEN** the files are copied, the worktree still matches HEAD, and the run records `copy`

#### Scenario: A file edited while it is cloned
- **WHEN** a file changes in the theatre after troupe found it matched HEAD and before it was cloned
- **THEN** the worktree's copy is checked out again from HEAD before the runner starts

#### Scenario: Before the worktree is made
- **WHEN** a worktree run's start is recorded and its worktree isn't made yet
- **THEN** its summary's workspace names the worktree's path and base, and has no clone mechanisms

### Requirement: Discarding removes the worktree
`discard` SHALL remove a run's worktree and change nothing in the theatre's working tree. The diff's artifact SHALL be
kept. Discarding an interrupted run, a run whose changes are `none`, or a run that couldn't start, SHALL remove its
worktree too. When the worktree is already gone, or was only partly made, discarding SHALL remove what is left of it,
including its registration with git, and succeed.

#### Scenario: Discarding a run
- **WHEN** a person discards a run that changed `src/a.txt`
- **THEN** the run's worktree is gone, the theatre's `src/a.txt` is unchanged, and the run's changes are `discarded`

#### Scenario: Discard says what it doesn't undo
- **WHEN** a person discards a run, or reads `troupe discard --help`
- **THEN** it says that discarding removes the worktree's files, and doesn't undo branches, tags, stashes, config,
  hooks or pushes the actor made in the shared repository

#### Scenario: Discarding an interrupted run
- **WHEN** a person discards a run that is `interrupted`
- **THEN** its worktree is removed and its discard is recorded

#### Scenario: Discarding a run that couldn't start
- **WHEN** a worktree run's worktree was made, and the run ended `could-not-start` before its runner started
- **THEN** its changes are `uncaptured`, with the worktree's path, and discarding it removes the worktree

#### Scenario: Discarding a run whose worktree is gone
- **WHEN** a person discards a run whose worktree directory doesn't exist
- **THEN** the discard succeeds and is recorded, and git has no worktree registered at its path
