# quality-check Specification

## Purpose

What troupe's `scripts/check.py` runs, the scoped form that narrows its tests, and troupe's declaration of which
paths need which part of the check. The commit guard and CI read that declaration, and every test run keeps it true.

## Requirements

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

### Requirement: A scoped check runs every gate and narrows only the tests
`scripts/check.py` SHALL accept `--scope <name>`, one or more times. With scopes, it SHALL run every gate the full
check runs, in the same order, and SHALL narrow only the tests, to those tagged with any of the given scopes. Without
`--scope`, it SHALL run exactly what it runs today.

#### Scenario: The docs scope
- **WHEN** a developer runs `uv run scripts/check.py --scope docs`
- **THEN** ruff, mypy and the import contracts run as in the full check
- **AND** only the tests tagged `docs` run

#### Scenario: A scope named twice
- **WHEN** a developer runs `uv run scripts/check.py --scope docs --scope docs`
- **THEN** the check runs as it does for `--scope docs`

#### Scenario: A failing gate in a scoped check
- **WHEN** a scoped check runs and a lint, type or test gate fails
- **THEN** the check stops and fails, naming the gate, as the full check does

### Requirement: An undeclared scope is refused before any gate runs
`scripts/check.py` SHALL refuse a scope that `scripts/check-paths.toml` doesn't declare, before running any gate. The
refusal SHALL name the scope, the file, and the fix. A malformed declaration SHALL be refused the same way, with the
guard's message, never treated as absent.

#### Scenario: A mistyped scope
- **WHEN** a developer runs `uv run scripts/check.py --scope nope`
- **THEN** the check fails without running any gate, naming `nope` and `scripts/check-paths.toml`

#### Scenario: A malformed declaration with a scope requested
- **WHEN** `scripts/check-paths.toml` is malformed and a developer runs `uv run scripts/check.py --scope docs`
- **THEN** the check fails without running any gate, saying what is wrong with the file and how to fix it

### Requirement: A scope with no tagged tests passes and says so
When every other gate passes and no test is tagged with any of the requested scopes, a scoped check SHALL pass, and
SHALL say that there was nothing to test. The full check SHALL still fail if it collects no tests.

#### Scenario: No tests carry the tag
- **WHEN** `scripts/check.py --scope docs` runs, every other gate passes, and no test is tagged `docs`
- **THEN** the check passes and says no test is tagged `docs`

### Requirement: The documentation tests carry the docs tag
Every test that reads a file the `docs` scope covers SHALL be tagged `docs`. The tag SHALL go on whole modules
when every test in the module reads the docs, and on single tests otherwise, so a scoped run doesn't run tests that
read nothing the scope covers.

#### Scenario: The tests that check the docs against the code
- **WHEN** `scripts/check.py --scope docs` runs
- **THEN** the tests that compare `docs/` with the code run, including the CLI, runs, runners, event store, exit codes
  and platform documentation tests, and the scripted runner's README options test
- **AND** no other test runs

### Requirement: Every test run keeps the declaration true
Every pytest run in this repository, full or scoped, in one process or in parallel, SHALL fail a test that reads a file
under a scope's paths without that scope's tag, or reads a file under `openspec/`. The failure SHALL name the test, the
file, and the tag to add or the skip entry it contradicts.

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

#### Scenario: An untagged doc read in a parallel run
- **WHEN** the tests run in parallel and a test in any worker reads `docs/runs.md` without the `docs` tag
- **THEN** that test fails, naming itself, `docs/runs.md` and the `docs` tag, as it does in one process

### Requirement: The check runs the tests in parallel
`scripts/check.py` SHALL run the tests across several worker processes, one for each CPU it may use, on Linux, macOS
and Windows. A scoped check SHALL run its tests the same way. The tests gate SHALL pass or fail on the same results
as a run in one process, with the same summary of failures.

#### Scenario: The full check on a machine with several CPUs
- **WHEN** a developer runs `uv run scripts/check.py` on a machine that lets it use 4 CPUs
- **THEN** the tests run in 4 worker processes, and the check passes only if every test passes

#### Scenario: A scoped check
- **WHEN** a developer runs `uv run scripts/check.py --scope docs`
- **THEN** only the tests tagged `docs` run, across the worker processes

#### Scenario: A failing test in a parallel run
- **WHEN** one test fails while the check runs the tests in parallel
- **THEN** the tests gate fails, the check stops naming that gate, and pytest's summary names the failing test

#### Scenario: A scope with no tagged tests in a parallel run
- **WHEN** a scoped check runs in parallel, every other gate passes, and no test carries the scope's tag
- **THEN** the check passes and says no test is tagged with that scope

### Requirement: Running pytest directly stays one process
Running pytest directly, without `scripts/check.py`, SHALL run the tests in one process, as before, unless the person
asks for workers themselves.

#### Scenario: One test run on its own
- **WHEN** a developer runs `uv run pytest packages/troupe/tests/test_cli.py -k usage`
- **THEN** the selected tests run in the developer's own pytest process, with no worker processes

### Requirement: A full run checks every catalogued code was raised, however it is split
A full pytest run (every test path, with no `-k`, `-m`, `--lf` or `--deselect`) SHALL fail when a catalogued error or
notice code was never constructed by troupe's own source, and SHALL name each such code. The check SHALL consider
every code raised in any worker process, and SHALL run once per run, never in each worker.

#### Scenario: Codes raised in different workers
- **WHEN** a full parallel run passes, and each catalogued code is raised by troupe's source in some worker, but no
  single worker raises them all
- **THEN** the run passes

#### Scenario: A code no worker raised
- **WHEN** a full parallel run passes its tests, and no worker's tests make troupe's source raise one catalogued code
- **THEN** the run fails once, naming that code as unexercised

#### Scenario: A partial run
- **WHEN** a run selects tests with `-k`, `-m`, `--lf` or `--deselect`, in one process or in parallel
- **THEN** the run does not check which codes were raised

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
registers in; or when they name the package's module or command, or a path into its directory, written in the code.

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
