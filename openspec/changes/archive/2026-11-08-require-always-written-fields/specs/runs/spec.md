## ADDED Requirements

### Requirement: A run's start always records its workspace
A run's start SHALL always record its workspace, and SHALL NOT record a worktree's clone mechanisms, which are recorded
once the worktree is made. A start without its workspace, or with clone mechanisms in it, SHALL NOT validate.

#### Scenario: A start without its workspace
- **WHEN** a run's start payload has no `workspace`
- **THEN** it doesn't validate against the run's start schema

#### Scenario: A start that holds clone mechanisms
- **WHEN** a worktree run's start payload holds `clones` in its workspace
- **THEN** it doesn't validate against the run's start schema, since a run's clone mechanisms are recorded only when
  its worktree is made

### Requirement: The reported runner comes from the run's init
A run's summary SHALL report the runner's name and version from its `init` event when the runner sent one, and SHALL
leave the reported runner out when it never did. The run's start SHALL NOT record the reported runner.

#### Scenario: A runner that never sent init
- **WHEN** a run ends before its runner sends an init
- **THEN** its start has no `runner_reported`, and the run's summary has no `runner.reported`

#### Scenario: A start that names the reported runner
- **WHEN** a run's start payload holds `runner_reported`
- **THEN** it doesn't validate against the run's start schema

### Requirement: A run's end records its audit whenever its runner started
A run's end SHALL record `outcome.audit` exactly when its runner started. It SHALL hold either `outside`, every change
outside the declaration in path order, each with `path`, `change`, `needs` and, for a move, `to`, and empty when every
change was declared; or `error`, when the audit couldn't read the workspace. An end whose runner started and that has
no `audit` SHALL NOT validate.

#### Scenario: A cancelled worktree run's end
- **WHEN** a worktree run whose actor declares no effects writes `src/a.py` and is cancelled
- **THEN** its end records outcome `cancelled`, and `outcome.audit.outside` holds `src/a.py`, `added`, needing
  `write`, alongside its `changes`

#### Scenario: A run that succeeded
- **WHEN** a run's changes are all declared and it succeeds
- **THEN** its end records `outcome.audit` with an empty `outside`

#### Scenario: A run whose runner never started has no audit
- **WHEN** a run's runner can't be started
- **THEN** its end has no `outcome.audit`

#### Scenario: An audit that contradicts itself
- **WHEN** a run's end payload has an `outcome.audit` with both `outside` and `error`, or with neither
- **THEN** it doesn't validate against the run's end schema

#### Scenario: An end without its audit
- **WHEN** a run's end payload has ending `exited` or `killed` and no `outcome.audit`
- **THEN** it doesn't validate against the run's end schema

## REMOVED Requirements

### Requirement: A run's summary leaves out a runner that never reported
**Reason**: Replaced by "The reported runner comes from the run's init", which keeps its rule and drops the scenario
in which a start recorded by an older troupe, holding `runner_reported`, still reads. There are no such records.
**Migration**: None. troupe hasn't written `runner_reported` since a run's start came before its runner.

### Requirement: A run's end records its audit
**Reason**: Replaced by "A run's end records its audit whenever its runner started", which keeps its rule, requires the
audit wherever the runner started, and drops the scenario in which an end recorded before audits still reads. There
are no such records.
**Migration**: None. troupe has recorded an audit in every end whose runner started since #272.
