## ADDED Requirements

### Requirement: A run's end records its audit
A run's end SHALL record `outcome.audit` exactly when its runner started. It SHALL hold either `outside`, every change
outside the declaration in path order, each with `path`, `change`, `needs` and, for a move, `to`, and empty when every
change was declared; or `error`, when the audit couldn't read the workspace. An end recorded before audits were
recorded has no `audit`, and SHALL still be read.

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

#### Scenario: An end recorded before audits were
- **WHEN** a run's end was recorded with no `outcome.audit`, and a person asks for its status
- **THEN** status reports the run with its outcome and no audit
