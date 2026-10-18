# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Every test run keeps the declaration true
Every pytest run in this repository, full or scoped, in one process or in parallel, SHALL fail a test that reads a file
under a `docs` path without the `docs` tag, or reads a file under `openspec/`. The failure SHALL name the test, the
file, and the tag to add or the skip entry it contradicts.

#### Scenario: A new doc test without its tag
- **WHEN** a test reads `docs/runs.md` and isn't tagged `docs`
- **THEN** that test fails, naming itself, `docs/runs.md` and the `docs` tag

#### Scenario: A test that reads OpenSpec artifacts
- **WHEN** a test reads a file under `openspec/`
- **THEN** that test fails, naming the file and the `openspec/**` skip entry

#### Scenario: An untagged doc read in a parallel run
- **WHEN** the tests run in parallel and a test in any worker reads `docs/runs.md` without the `docs` tag
- **THEN** that test fails, naming itself, `docs/runs.md` and the `docs` tag, as it does in one process
