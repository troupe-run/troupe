# quality-check Specification

## Purpose

Capability: `cap:development`

What troupe's `scripts/check.py` runs, the scoped form that narrows its tests, and troupe's declaration of which
paths need which part of the check. The commit guard and CI read that declaration, and every test run keeps it true.

## Requirements

### Requirement: The declaration skips OpenSpec artifacts and scopes the docs
troupe SHALL declare in `scripts/check-paths.toml` that `openspec/**` needs no check. It SHALL declare a scope
`docs`, covering `docs/**`, `contributing/**` and `plugins/runner-scripted/README.md`, and the package and `scripts`
scopes that the requirements below name. Any other path SHALL be in neither group, so a change to it runs the full
check.

#### Scenario: A commit that stages only OpenSpec artifacts
- **WHEN** a commit stages only files under `openspec/`, such as an archive or a task tick
- **THEN** the commit guard skips the check, naming `openspec/**` and `scripts/check-paths.toml`

#### Scenario: A commit that stages only documentation
- **WHEN** a commit stages only files under `docs/` or `contributing/`, possibly with files under `openspec/`
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
- **THEN** the tests that compare `docs/` and `contributing/` with the code run, including the CLI reference, runs,
  runners, event store, exit codes and platform documentation tests, and the scripted runner's README options test
- **AND** the tests of the user docs' front matter, links, vocabulary, changelog page and generated regions run
- **AND** no other test runs

### Requirement: Every test run keeps the declaration true
Every pytest run in this repository, full or scoped, in one process or in parallel, SHALL fail a test that reads a file
under a scope's paths without that scope's tag, or reads a file under `openspec/`. The failure SHALL name the test, the
file, and the tag to add or the skip entry it contradicts.

#### Scenario: A new doc test without its tag
- **WHEN** a test reads `contributing/runs.md` and isn't tagged `docs`
- **THEN** that test fails, naming itself, `contributing/runs.md` and the `docs` tag

#### Scenario: A test that reads another package's files untagged
- **WHEN** a test outside the scripted runner's reach reads a file under `plugins/runner-scripted/` and isn't tagged
  `runner_scripted`
- **THEN** that test fails, naming itself, the file and the `runner_scripted` tag

#### Scenario: A test that reads OpenSpec artifacts
- **WHEN** a test reads a file under `openspec/`
- **THEN** that test fails, naming the file and the `openspec/**` skip entry

#### Scenario: An untagged doc read in a parallel run
- **WHEN** the tests run in parallel and a test in any worker reads `contributing/runs.md` without the `docs` tag
- **THEN** that test fails, naming itself, `contributing/runs.md` and the `docs` tag, as it does in one process

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

### Requirement: The check prints the slowest tests on every run
`scripts/check.py` SHALL have its tests gate print the 25 slowest test phases with their durations, in the full check
and in every scoped check, locally and in CI on Linux, macOS and Windows. It SHALL print them when the tests pass and
when they fail, and the durations SHALL NOT change whether the gate passes or fails.

#### Scenario: A full check that passes
- **WHEN** a developer runs `uv run scripts/check.py` and every gate passes
- **THEN** the tests gate's output lists the slowest 25 durations, each naming its test and how long it took

#### Scenario: A scoped check
- **WHEN** a developer runs `uv run scripts/check.py --scope docs`
- **THEN** the tests gate's output lists the slowest durations among the tests tagged `docs`

#### Scenario: A failing test
- **WHEN** a test fails while the check runs the tests in parallel
- **THEN** the tests gate fails as before, naming the failing test, and its output still lists the slowest durations

#### Scenario: A CI job
- **WHEN** the check runs in a CI job on any platform
- **THEN** the job's log lists the slowest 25 durations

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

### Requirement: A pull request's CI runs only what its changed paths need
CI SHALL work out the changed paths of a pull request that's ready for review, since the last push whose `check`
passed, or from its base when no earlier push passed, and ask the declaration in `scripts/check-paths.toml` what they
need, through the same decision the commit guard makes. Every leg of the test matrix SHALL then skip the check, run the
scoped check, or run the full check, as that answer says.

#### Scenario: A pull request that changes only OpenSpec artifacts
- **WHEN** a pull request's changes are all under `openspec/`, such as a change's archive and its task ticks
- **THEN** no leg installs the project or runs `scripts/check.py`
- **AND** every required check passes

#### Scenario: A pull request that changes only documentation
- **WHEN** a pull request's changes are all under `docs/`, possibly with files under `openspec/`
- **THEN** every leg runs `scripts/check.py --scope docs`

#### Scenario: A pull request that changes two packages
- **WHEN** a pull request changes files under `packages/troupe-vcs-git/` and `packages/troupe-store-text/` only
- **THEN** every leg runs `scripts/check.py --scope store_text --scope vcs_git`

#### Scenario: A pull request that changes anything else
- **WHEN** a pull request changes a path in no group, such as core code, CI configuration, `scripts/check-paths.toml`
  or the root `README.md`
- **THEN** every leg runs the full check

### Requirement: A push is checked against the last push that passed
When a push adds to an open pull request and the latest `check` on the previous head, reported by GitHub Actions,
passed, CI SHALL work out the changed paths by comparing the previous head's tree with the new head's. Otherwise it
SHALL use every path the pull request changes from its base.

#### Scenario: An archive push after a green code push
- **WHEN** a pull request's code changes passed `check`, and the next push only moves files under `openspec/`
- **THEN** no leg installs the project or runs `scripts/check.py`
- **AND** every required check passes

#### Scenario: A push after a run that didn't pass
- **WHEN** the previous head's `check` failed, was cancelled, hasn't finished or never ran, and the next push changes
  only files under `openspec/`
- **THEN** CI uses every path the pull request changes, and runs the check those paths need

#### Scenario: A docs-only push after a green code push
- **WHEN** a pull request's code changes passed `check`, and the next push changes only files under `docs/`
- **THEN** every leg runs `scripts/check.py --scope docs`

#### Scenario: A force push
- **WHEN** a pull request whose head passed `check` is force-pushed with a rewritten history, and the new head's tree
  differs from the old one only under `openspec/`
- **THEN** no leg runs `scripts/check.py`, and every required check passes

#### Scenario: The previous head is gone
- **WHEN** the previous head can't be found in the repository
- **THEN** CI uses every path the pull request changes

#### Scenario: A check of the same name from another app
- **WHEN** the previous head has a passing check named `check` reported by an app other than GitHub Actions, and none
  from GitHub Actions
- **THEN** CI uses every path the pull request changes

#### Scenario: The previous head was only checked as a draft
- **WHEN** a draft is marked ready, and a push that changes only files under `openspec/` arrives before the ready
  run's `check` on the previous head has reported
- **THEN** CI uses every path the pull request changes, and runs the check those paths need

#### Scenario: The previous head passed once it was ready
- **WHEN** a draft was marked ready and the ready run's `check` passed on its head, and the next push changes only
  files under `openspec/`
- **THEN** no leg runs `scripts/check.py`, and every required check passes

### Requirement: CI runs the full check when the changed paths are unknown
When CI can't work out a pull request's changed paths, or can't get an answer from the declaration, every leg SHALL
run the full check. A skip SHALL happen only when the changed paths are known and every one is skipped.

#### Scenario: The changed paths can't be worked out
- **WHEN** the step that lists a pull request's changed paths fails, or lists none
- **THEN** every leg runs the full check

#### Scenario: A malformed input to the decision
- **WHEN** a sha CI is given isn't a 40-character hexadecimal sha, or the event's action isn't one CI runs on
- **THEN** the step that decides fails, naming the input and what's valid, and every leg runs the full check

#### Scenario: A malformed declaration
- **WHEN** a pull request makes `scripts/check-paths.toml` malformed
- **THEN** every leg runs the full check, which fails, naming the file and what is wrong with it

### Requirement: A push to main skips a commit the merge queue passed
On a push to `main`, CI SHALL skip every leg when its own merge-queue run on that exact commit succeeded, and `check`
SHALL pass. Any other push to `main` SHALL run the full check on every leg. Finding out SHALL never fail CI's run:
when it can't be found out, every leg runs the full check.

#### Scenario: A merge through the queue
- **WHEN** the merge queue passes a merge group and its commit lands on `main`
- **THEN** CI's run on `main` runs no leg, `check` passes, and the run succeeds

#### Scenario: A commit that didn't come through the queue
- **WHEN** a commit reaches `main` with no merge-queue run of CI on it, such as a guard delivery
- **THEN** every leg runs the full check on `main`

#### Scenario: A merge-queue run on the commit that didn't pass
- **WHEN** CI's only merge-queue runs on the commit pushed to `main` failed or were cancelled
- **THEN** every leg runs the full check on `main`

#### Scenario: The merge-queue run is still finishing
- **WHEN** CI's merge-queue run on the commit hasn't completed when the push's run asks
- **THEN** CI waits for it for a bounded time, skips the legs if it succeeds in that time, and otherwise runs the full
  check

#### Scenario: The merge-queue runs can't be read
- **WHEN** reading CI's merge-queue runs fails, or answers in a shape CI doesn't recognise
- **THEN** CI warns, naming why, and every leg runs the full check
- **AND** the read itself doesn't fail the run

### Requirement: A draft pull request runs no legs until it's marked ready
On a draft pull request, CI SHALL run no leg, and `check` SHALL be skipped rather than pass. Marking the pull request
ready for review SHALL run what every path the pull request changes from its base needs.

#### Scenario: A push to a draft
- **WHEN** a draft pull request is opened, or a push adds to one, whatever it changes
- **THEN** no leg installs the project or runs `scripts/check.py`
- **AND** `check` is skipped, saying it runs when the pull request is marked ready

#### Scenario: A draft marked ready
- **WHEN** a draft whose changes include core code is marked ready for review
- **THEN** every leg runs the full check, judged on every path the pull request changes from its base

#### Scenario: A draft marked ready whose changes are all OpenSpec artifacts
- **WHEN** a draft whose changes are all under `openspec/` is marked ready for review
- **THEN** no leg runs `scripts/check.py`, and `check` passes

### Requirement: Every merge group runs the full check
CI SHALL run on every merge group the merge queue creates for `main`, and SHALL run the full check there on every
leg, whatever its pull requests changed. No trigger filter or changed-path answer SHALL skip or narrow the check on a
merge group, since the queue lands only a commit whose required checks reported on it.

#### Scenario: A merge group of pull requests that change only OpenSpec artifacts
- **WHEN** the merge queue builds a merge group from pull requests whose changes are all under `openspec/`
- **THEN** every leg runs the full check on the merge group's commit
- **AND** `check` reports on that commit

#### Scenario: A merge group of pull requests that change code
- **WHEN** the merge queue builds a merge group from a pull request that changes core code
- **THEN** every leg runs the full check on the merge group's commit, and `check` passes only when every leg passed

#### Scenario: The workflow gains a path filter
- **WHEN** a change adds a path filter to any of CI's triggers, or lets the job that works out changed paths run on a
  merge group
- **THEN** the full check fails, naming the workflow and what would skip the check on the queue

### Requirement: One required check reports for every leg
CI SHALL report one check named `check` on every pull request that's ready for review, every merge group and every
push to `main`. It SHALL pass when every leg passed, or when every leg was skipped because the changed paths needed no
check or the merge queue had passed the commit. It SHALL fail when any leg failed or was cancelled, and when the legs
were skipped for any other reason.

#### Scenario: Every leg passes
- **WHEN** every leg runs and passes
- **THEN** `check` passes

#### Scenario: One leg fails
- **WHEN** every leg runs and one fails
- **THEN** `check` fails

#### Scenario: The legs are skipped because nothing needs checking
- **WHEN** the changed paths are all skipped, and so every leg is skipped
- **THEN** `check` passes

#### Scenario: The legs are skipped without that answer
- **WHEN** every leg is skipped, but the answer wasn't that nothing needs checking
- **THEN** `check` fails, saying the legs were skipped without a reason to skip them

#### Scenario: A merge group's legs pass
- **WHEN** every leg runs the full check on a merge group's commit and passes
- **THEN** `check` passes on that commit

#### Scenario: A push to main the merge queue passed
- **WHEN** every leg is skipped on a push to `main` because the merge queue passed that commit
- **THEN** `check` passes

### Requirement: No gate reads OpenSpec artifacts
No gate in `scripts/check.py` SHALL read a file under `openspec/`, so that skipping the check for a change to those
files skips nothing that could fail.

#### Scenario: A badly formatted code block in an OpenSpec artifact
- **WHEN** a Markdown file under `openspec/` holds a Python code block that ruff would reformat
- **THEN** `scripts/check.py`'s format gate passes

#### Scenario: The same block in the documentation
- **WHEN** a Markdown file under `docs/` holds the same code block
- **THEN** the format gate fails, naming the file
