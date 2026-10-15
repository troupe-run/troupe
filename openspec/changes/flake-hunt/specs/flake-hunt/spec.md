# Spec Delta

## Purpose

Finding flaky tests on demand, on every platform: repeating tests in overlapping rounds, under optional load and with
fresh randomised inputs, and reporting each failure with the evidence an issue needs.

## ADDED Requirements

### Requirement: The hunt repeats tests in overlapping rounds
`scripts/flake_hunt.py`, run with `uv run`, SHALL run the selected tests for a given number of rounds in a given
number of workers at once. Each worker SHALL run its rounds back to back, so the workers' rounds overlap. Each round
SHALL be a separate pytest process with its own temporary directory. Without a selection, the hunt SHALL run every
test the repository's pytest configuration collects.

#### Scenario: Rounds in parallel workers
- **WHEN** the hunt runs with 3 workers and 4 rounds
- **THEN** it runs 12 rounds, 3 at a time, and reports all 12

#### Scenario: A selection by path and keyword
- **WHEN** the hunt is given test paths and a `-k` expression
- **THEN** every round runs exactly the tests pytest selects for those paths and that expression

#### Scenario: No selection
- **WHEN** the hunt is given no paths and no `-k`
- **THEN** every round runs the whole suite the pytest configuration collects

### Requirement: The hunt can load the machine
The hunt SHALL keep a given number of CPUs busy for as long as its rounds run, and SHALL stop that load when it ends,
however it ends. With no load given, it SHALL add none.

#### Scenario: Load during the rounds
- **WHEN** the hunt runs with a load of 2
- **THEN** two busy processes run from before the first round starts until the last round ends, and none is left
  running afterwards

#### Scenario: Stopped part-way
- **WHEN** the person presses Ctrl-C during a hunt
- **THEN** the running rounds and the load stop, the summary of the rounds that finished is printed, and no process
  the hunt started is left running

### Requirement: Every round explores new randomised inputs
Each round SHALL give hypothesis its own empty example database, so no round replays an example an earlier round or
an earlier commit saved. The hunt SHALL NOT read or write the repository's `.hypothesis/` directory.

#### Scenario: A hypothesis failure in one round
- **WHEN** a hypothesis test fails in one round
- **THEN** later rounds don't replay its example, and the repository's `.hypothesis/` directory is unchanged

### Requirement: The hunt reports each failing test with its evidence
The hunt SHALL print each round's outcome as the round ends. When it ends, it SHALL print a summary naming every test
that failed or errored in any round, with the number of rounds that ran it, the number that failed, and the first
failure's message and traceback. The summary SHALL name the platform, the Python version, the workers, the rounds and
the load. A round that ends without a test report SHALL be reported as a failed round, with its output.

#### Scenario: A test that fails in some rounds
- **WHEN** a test fails in 2 of 12 rounds
- **THEN** the summary names that test with 12 runs and 2 failures, and shows the first failure's message and
  traceback

#### Scenario: A round that crashes
- **WHEN** a round's pytest process ends without writing its report
- **THEN** that round is reported as failed, with the end of its output

#### Scenario: A clean hunt
- **WHEN** no test fails in any round
- **THEN** the summary says how many rounds ran and that none failed, and the hunt exits 0

### Requirement: The hunt's results are kept as data
The hunt SHALL write its results as JSON to an output directory it names: one record per round (its worker, round,
exit code, duration and every failure with its test, message and traceback) and the summary, with the platform,
Python version and options. A hunt in which any round failed SHALL exit non-zero.

#### Scenario: Results for an issue
- **WHEN** a hunt ends
- **THEN** its output directory holds the JSON results and each round's pytest output, and the hunt prints where

### Requirement: The hunt refuses malformed options
A number of workers, rounds or load that isn't a whole number, is below its minimum (1 worker, 1 round, 0 load) or
asks for more load than the machine has CPUs SHALL be refused before anything runs, with an error naming the option,
the value and what is allowed.

#### Scenario: Too much load
- **WHEN** the hunt is asked for more load than the machine has CPUs
- **THEN** it runs nothing and exits with an error naming the load, the value and the number of CPUs

#### Scenario: Zero rounds
- **WHEN** the hunt is asked for 0 rounds
- **THEN** it runs nothing and exits with an error naming the rounds option and its minimum

### Requirement: The hunt runs on every platform
The hunt SHALL run on Linux, macOS and Windows with the same options and output. How to run it on each, including
Linux in Docker as an ordinary user with an init process that reaps orphans, SHALL be documented.

#### Scenario: Linux in Docker
- **WHEN** someone follows the documented steps for Linux
- **THEN** the hunt runs in a container as a user other than root, with an init process as PID 1, on a copy of the
  repository inside the container
