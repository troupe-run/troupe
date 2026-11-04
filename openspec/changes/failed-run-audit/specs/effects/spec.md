## MODIFIED Requirements

### Requirement: Every run's changes are audited against its declaration
Once a run's runner has ended, whatever the run's outcome, troupe SHALL audit each file added, changed or removed in
its workspace since the run started. Every change the declaration doesn't allow SHALL fail the audit. The audit SHALL
run for every actor, whatever its `expect`, and for every run whose runner started. A run whose runner never started
SHALL have no audit. When the run's result is `ok`, the audit SHALL be part of its effect check.

#### Scenario: Expecting nothing still audits
- **WHEN** an actor has `expect: []`, declares no effects, and its run writes `out/a.txt`
- **THEN** the audit fails, and the run doesn't succeed

#### Scenario: A run that failed is audited
- **WHEN** an actor declares `write` for `out/**`, and its run changes `src/a.py` and then sends an `error` result
- **THEN** the run's audit names `src/a.py` and the `write` effect it needed

#### Scenario: A run whose runner never started
- **WHEN** a run's runner can't be started
- **THEN** the run has no audit

## ADDED Requirements

### Requirement: A failed run's audit doesn't change its outcome
When a run's result isn't `ok`, or it sent none, its audit SHALL NOT change its outcome or its error: the run keeps
the one error it failed with. Its findings SHALL be recorded with the run's end, as for any run, and a worktree run's
changes SHALL be kept, to show, accept or discard. Its expected files SHALL NOT be checked.

#### Scenario: A failed run that changed a file outside its declaration
- **WHEN** a worktree run whose actor declares `write` for `out/**` changes `src/a.py` and sends an `error` result
- **THEN** its outcome is `failed` with `run.error-result`, its end records the audit naming `src/a.py` and `write`,
  and its changes are kept

#### Scenario: A timed-out run that changed a file outside its declaration
- **WHEN** a run whose actor declares no effects writes `notes.md` and is still going when its run timeout passes
- **THEN** its outcome is `timed-out` with `run.timeout`, and its end records the audit naming `notes.md` and `write`

#### Scenario: A cancelled run that removed a file outside its declaration
- **WHEN** a run whose actor declares `write` for `**` removes `README.md` and is then cancelled
- **THEN** its outcome is `cancelled` with no error, and its end records the audit naming `README.md` and `delete`

#### Scenario: A failed run that stayed inside its declaration
- **WHEN** a run whose actor declares `write` for `out/**` changes only `out/a.txt` and sends an `error` result
- **THEN** its end records an audit that found no change outside the declaration

#### Scenario: A failed run's expected file
- **WHEN** a run whose actor expects `out/hello.txt` sends an `error` result without writing it
- **THEN** its error is `run.error-result` alone, and doesn't name `out/hello.txt`

### Requirement: An audit that can't read the workspace says so
When the audit can't read the workspace's files, the run's end SHALL still be recorded, holding the audit's error in
place of its findings. For a run whose result is `ok`, the effect check SHALL fail with `effects.audit-failed`, naming
the error, so the run doesn't succeed. For any other run, the outcome and its error SHALL be unchanged.

#### Scenario: The workspace can't be read after an ok result
- **WHEN** a runner sends an `ok` result and exits 0, and reading the workspace's files for the audit fails
- **THEN** the run's outcome is `failed` with `effects.audit-failed`, and its end records the audit's error

#### Scenario: The workspace can't be read after a cancel
- **WHEN** a run is cancelled, and reading the workspace's files for the audit fails
- **THEN** the run's outcome is `cancelled`, and its end records the audit's error
