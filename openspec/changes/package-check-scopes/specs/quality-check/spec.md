# Spec Delta

## MODIFIED Requirements

### Requirement: The declaration skips OpenSpec artifacts and scopes the docs
troupe SHALL declare in `scripts/check-paths.toml` that `openspec/**` needs no check. It SHALL declare a scope
`docs`, covering `docs/**` and `plugins/runner-scripted/README.md`, and the package and `scripts` scopes that the
requirements below name. Any other path SHALL be in neither group, so a change to it runs the full check.

#### Scenario: A commit that stages only OpenSpec artifacts
- **WHEN** a commit stages only files under `openspec/`, such as an archive or a task tick
- **THEN** the commit guard skips the check, naming `openspec/**` and `scripts/check-paths.toml`

#### Scenario: A commit that stages only documentation
- **WHEN** a commit stages only files under `docs/`, possibly with files under `openspec/`
- **THEN** the commit guard runs `scripts/check.py --scope docs` instead of the full check, and says so

#### Scenario: A commit that changes the scripted runner's README
- **WHEN** a commit stages only `plugins/runner-scripted/README.md`
- **THEN** the commit guard runs `scripts/check.py --scope docs --scope runner_scripted`, because the path is in both
  scopes

#### Scenario: A commit that stages anything else
- **WHEN** a commit stages a path in no scope, such as core code, a check or guard file, CI configuration, `protocol/`
  or the root `README.md`
- **THEN** the commit guard runs the full check

### Requirement: Every test run keeps the declaration true
Every pytest run in this repository, full or scoped, SHALL fail a test that reads a file under a scope's paths
without that scope's tag, or reads a file under `openspec/`. The failure SHALL name the test, the file, and the tag
to add or the skip entry it contradicts.

#### Scenario: A new doc test without its tag
- **WHEN** a test reads `docs/runs.md` and isn't tagged `docs`
- **THEN** that test fails, naming itself, `docs/runs.md` and the `docs` tag

#### Scenario: A test that reads another package's files untagged
- **WHEN** a test outside the scripted runner's reach reads a file under `plugins/runner-scripted/` and isn't tagged
  `runner_scripted`
- **THEN** that test fails, naming itself, the file and the `runner_scripted` tag

#### Scenario: A test that reads OpenSpec artifacts
- **WHEN** a test reads a file under `openspec/`
- **THEN** that test fails, naming the file and the `openspec/**` skip entry

## ADDED Requirements

### Requirement: Each package outside core has a scope
troupe SHALL declare one scope per workspace package other than core: `artifacts_local`, `identity_local`,
`stage_local`, `store_text`, `vcs_files` and `vcs_git` for `packages/troupe-<name>/`, and `runner_scripted` for
`plugins/runner-scripted/`. Each SHALL cover its package's files except `pyproject.toml`. Core, `packages/troupe/**`,
and every package's `pyproject.toml` SHALL be in no scope, so a change to them runs the full check.

#### Scenario: A commit that changes one leaf package
- **WHEN** a commit stages only files under `packages/troupe-stage-local/`, possibly with files under `openspec/`
- **THEN** the commit guard runs `scripts/check.py --scope stage_local`
- **AND** every gate runs, and the tests that run are the stage-local suite and the suites that reach it

#### Scenario: A commit that changes two packages
- **WHEN** a commit stages files under `packages/troupe-vcs-git/` and `packages/troupe-store-text/`
- **THEN** the commit guard runs `scripts/check.py --scope store_text --scope vcs_git`, and the tests that run are
  every suite that reaches either package

#### Scenario: A commit that changes core
- **WHEN** a commit stages any file under `packages/troupe/`, including core's shared test helpers
- **THEN** the commit guard runs the full check

#### Scenario: A commit that changes a package's pyproject.toml
- **WHEN** a commit stages `packages/troupe-stage-local/pyproject.toml`, which can change the package's dependencies
  or entry points and so what reaches it
- **THEN** the commit guard runs the full check

#### Scenario: A package added later
- **WHEN** a commit adds a new directory under `packages/` or `plugins/` that no scope names
- **THEN** the commit guard runs the full check

### Requirement: The scripts have a scope that leaves out the check and the guard
troupe SHALL declare a scope `scripts` covering `scripts/tests/**` and each other file under `scripts/` by its exact
path, except `scripts/check.py`, `scripts/guard.py`, `scripts/guard_pytest.py` and `scripts/check-paths.toml`, which
SHALL be in no scope. A file added under `scripts/` SHALL be in no scope until it is declared.

#### Scenario: A commit that changes a script and its tests
- **WHEN** a commit stages only `scripts/flake_hunt.py` and `scripts/tests/test_flake_hunt.py`
- **THEN** the commit guard runs `scripts/check.py --scope scripts`
- **AND** every gate runs, and the only tests that run are those in the scripts suite

#### Scenario: A commit that changes the check or the guard
- **WHEN** a commit stages `scripts/check.py`, `scripts/guard.py` or `scripts/guard_pytest.py`
- **THEN** the commit guard runs the full check

#### Scenario: A new script
- **WHEN** a commit adds `scripts/new_tool.py` and the declaration doesn't name it
- **THEN** the commit guard runs the full check

### Requirement: A scope runs exactly the suites that reach it
Each package and `scripts` scope SHALL name the test suites it runs, and a scoped check SHALL run every test in those
suites. A suite reaches a package when its tests or the helpers they use import the package, directly or through
other packages' imports and dependencies; when they use core code that loads an entry-point group the package
registers in; or when they name the package's directory, module or command, as a file they read or a process they
start.

#### Scenario: The core suite reaches every adapter
- **WHEN** a scoped check runs for any package scope
- **THEN** the core suite runs, because core loads every entry-point group and starts the scripted runner

#### Scenario: A suite that doesn't reach the package
- **WHEN** `scripts/check.py --scope stage_local` runs
- **THEN** the scripted runner's suite doesn't run, and of the scripts suite only the reach check runs

### Requirement: Every package scope runs the reach check
A scoped check for any package scope SHALL also run the check that the scopes agree with their reach, because a change
to a package can change what reaches it.

#### Scenario: A package change that alters its reach
- **WHEN** a commit changes only `packages/troupe-artifacts-local/`, and its tests start importing `troupe_vcs_git`
- **THEN** the commit guard's `--scope artifacts_local` run fails, naming `vcs_git` and the artifacts-local suite

### Requirement: A full run fails when a scope's suites disagree with their reach
A full test run SHALL fail when any package or `scripts` scope names a suite that doesn't reach it, or leaves out a
suite that does. The failure SHALL name the scope, each suite added or missing, and the corrected list to declare.

#### Scenario: A suite starts importing another package
- **WHEN** a test in the artifacts-local suite imports `troupe_vcs_git`, and the `vcs_git` scope doesn't name that
  suite
- **THEN** the full run fails, naming `vcs_git`, the artifacts-local suite as missing, and the list to declare

#### Scenario: A scope names a suite that no longer reaches it
- **WHEN** a scope names a suite whose tests no longer reach the scope's package
- **THEN** the full run fails, naming the scope and the suite to remove
