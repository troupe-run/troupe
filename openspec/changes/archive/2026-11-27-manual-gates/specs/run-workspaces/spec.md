# Spec Delta

## MODIFIED Requirements

### Requirement: The worktree is kept until the changes are accepted or discarded
A run's worktree SHALL stay in place after the run ends, including the files git ignores, until its changes are
accepted, discarded or rejected, whether by a person or at a gate (spec: gates). It SHALL stay in place when the run
was interrupted, and while a cue for it is open. troupe SHALL NOT remove a worktree for any other reason.

#### Scenario: Ignored output survives the run
- **WHEN** a worktree run writes `build/out.bin`, which git ignores, and ends
- **THEN** `build/out.bin` is still in the run's worktree, and `status <run>` names the worktree's path

#### Scenario: A run waiting at a gate
- **WHEN** a worktree run ends with a cue open for `director`
- **THEN** its worktree is still there, and `status <run>` names its path

### Requirement: A run's changes have a state
A run summary SHALL give a worktree run's changes a state: `waiting` while a cue for them is open, `pending` when
the run's end recorded a diff and nothing has settled it or raised a cue, `accepted`, `discarded` or `rejected` once
that is recorded, `none` when the run changed nothing, and `uncaptured` when its end, or no end, holds no diff because
capturing failed or the run was interrupted. A run that didn't use a worktree SHALL have no changes state.

#### Scenario: After a run
- **WHEN** a worktree run that changed one file has ended `failed`
- **THEN** `status <run>` shows its changes as `pending`, with the diff's reference and the worktree's path

#### Scenario: A run in place
- **WHEN** a run's actor has workspace `theatre`
- **THEN** its summary has workspace `theatre` and no changes

#### Scenario: An interrupted run
- **WHEN** a worktree run's `perform` is killed
- **THEN** `status <run>` shows its changes as `uncaptured`, with the worktree's path

#### Scenario: Waiting at a gate
- **WHEN** a worktree run with approvers `[director]` changed one file and ended `succeeded`
- **THEN** `status <run>` shows its changes as `waiting`, for `director`, with the diff's reference and the
  worktree's path

#### Scenario: Rejected
- **WHEN** a person rejects a run's cue
- **THEN** `status <run>` shows its changes as `rejected`, with when, and no worktree

## ADDED Requirements

### Requirement: Accept and discard leave an open cue to its answer
While a run has an open cue, `accept` and `discard` SHALL be refused with `run.waiting-at-gate`, naming the role the
cue is for and the `troupe approve` or `troupe reject` command for the run, and SHALL change no file and record
nothing. A rehearsal SHALL be refused the same way.

#### Scenario: Accepting a waiting run
- **WHEN** a person runs `troupe accept <run>` on a run whose cue for `director` is open
- **THEN** it is refused with `run.waiting-at-gate`, naming `director` and `troupe approve <run>`
- **AND** no file changes, nothing is recorded, and the cue stays open

#### Scenario: Discarding a waiting run
- **WHEN** a person runs `troupe discard <run>` on a run whose cue is open
- **THEN** it is refused with `run.waiting-at-gate`, naming `troupe reject <run>`, and the worktree is still there

### Requirement: A run settled at a gate can't be settled again
Once a run's changes are `rejected`, a later `accept`, `discard`, `approve` or `reject` SHALL be refused with
`run.changes-settled`, naming the rejection and when, as for an acceptance or a discard.

#### Scenario: Accepting a rejected run
- **WHEN** a person rejects a run's cue and then accepts the run
- **THEN** the accept is refused with `run.changes-settled`, naming the rejection
