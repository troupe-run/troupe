## ADDED Requirements

### Requirement: Every test is unit or integration by its directory
Each suite's tests SHALL live in its `tests/unit/` or `tests/integration/` directory, and a test's directory SHALL be
its kind. Every pytest run SHALL tag each test `unit` or `integration` from its directory before `-m` selects, so each
test carries exactly one kind. A run that collects a test file outside both directories SHALL fail, whatever `-m`
selects and in one process or across workers, naming the file and the two directories.

#### Scenario: A test under unit
- **WHEN** pytest collects `packages/troupe/tests/unit/test_errors.py`
- **THEN** its tests carry the `unit` tag and not `integration`

#### Scenario: A new test file in neither directory
- **WHEN** a developer adds `packages/troupe/tests/test_new.py` and runs pytest
- **THEN** collecting the file fails, naming it and the suite's `tests/unit/` and `tests/integration/` directories,
  and the run fails, as it does with `-m unit`, `-m "not integration"` or across workers

#### Scenario: A hand-written kind
- **WHEN** a test is marked `pytest.mark.unit` or `pytest.mark.integration` by hand
- **THEN** that test fails, saying its directory gives its kind and the mark must go

### Requirement: Test modules share code only through helpers beside both kinds
No test module SHALL import another test module. Code that tests share SHALL live in helper modules in the suite's
`tests/` directory, beside `unit/` and `integration/`, so either kind can import it without depending on the other.
Every pytest run SHALL fail a test whose module imports a test module, naming both modules. A helper has no kind: a unit
test that reaches outside its process through a helper still fails as a unit test that reaches outside.

#### Scenario: A unit test module importing from an integration test module
- **WHEN** `tests/unit/test_a.py` has `from test_b import configured`, and `test_b.py` is under `tests/integration/`
- **THEN** the tests in `test_a.py` fail, naming `test_a.py` and `test_b`, and saying to move `configured` to a helper
  in `tests/`

#### Scenario: Two test modules of the same kind
- **WHEN** `tests/unit/test_a.py` imports `test_c`, and `test_c.py` is under `tests/unit/` too
- **THEN** the tests in `test_a.py` fail the same way

#### Scenario: A unit test that starts a process through a helper
- **WHEN** a test under `tests/unit/` calls a helper in `tests/` that runs git
- **THEN** it fails, naming a process running `git`

### Requirement: A unit test stays inside its process
Every pytest run, in one process or in parallel, SHALL fail a unit test that reaches outside its process, itself or
through a fixture it uses, even a fixture an earlier test set up. The failure SHALL name the test, what it reached
(each kind of access, with the program for a process), and the fix: move it to `tests/integration/`, or keep it
in-process. An integration test that reaches nothing SHALL pass.

#### Scenario: A unit test that runs git
- **WHEN** a test under `tests/unit/` builds a git theatre
- **THEN** it fails, naming itself, a process running `git`, and `tests/integration/`

#### Scenario: A unit test that talks to a stand-in server
- **WHEN** a test under `tests/unit/` sends a request to a stand-in server listening on loopback in a thread of the
  test's own process
- **THEN** it fails, naming itself and a socket

#### Scenario: Through a fixture set up earlier
- **WHEN** a session-scoped fixture started a process while an earlier test set it up, and a unit test uses it
- **THEN** that unit test fails too, naming the process

#### Scenario: A local socket pair
- **WHEN** a unit test makes a socket pair to wake a thread in its own process, on Linux, macOS or Windows
- **THEN** it passes: a socket pair links two ends in the same process

#### Scenario: An integration test that reaches nothing on this OS
- **WHEN** a test under `tests/integration/` starts a process only on Windows and runs on macOS
- **THEN** it passes

### Requirement: What reaching outside means is declared in one place
The kinds of access that make a test integration SHALL be declared in one place: starting a process, opening a
socket, network or Unix-domain, other than a socket pair, and being handed a git theatre. Adding a kind there SHALL make every unit test that uses it
fail on the next run, with no change to any test. Each declared kind SHALL have a test that a unit test using it fails
and an integration test using it passes.

#### Scenario: Every declared kind is caught
- **WHEN** the detector's own tests run
- **THEN** for each declared kind, a unit test using it fails naming the kind, and the same test under
  `tests/integration/` passes

### Requirement: The unit tests run on their own
A developer and a mutation run SHALL be able to run the unit tests alone: naming the suites' `tests/unit/`
directories, or selecting `-m unit` or `-m "not integration"`, which select the same tests. `scripts/check.py` and CI
SHALL still run both kinds, and no time limit SHALL apply to a unit test. Every run SHALL end by printing, for each
kind, how many of its tests ran and their summed time.

#### Scenario: Selecting the unit tests by tag
- **WHEN** a developer runs `uv run pytest -m unit`
- **THEN** every test under a `tests/unit/` directory runs, and no test under `tests/integration/` does
- **AND** the run ends by printing the number of unit tests that ran and their summed time

#### Scenario: The full check
- **WHEN** a developer runs `uv run scripts/check.py`
- **THEN** the unit and the integration tests both run

## MODIFIED Requirements

### Requirement: Running pytest directly stays one process
Running pytest directly, without `scripts/check.py`, SHALL run the tests in one process, as before, unless the person
asks for workers themselves.

#### Scenario: One test run on its own
- **WHEN** a developer runs `uv run pytest packages/troupe/tests/unit/test_cli.py -k usage`
- **THEN** the selected tests run in the developer's own pytest process, with no worker processes
