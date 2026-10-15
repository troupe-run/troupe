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
- **WHEN** the person presses Ctrl-C during a hunt, or Ctrl-Break on Windows
- **THEN** the running rounds and the load stop, the summary of the rounds that finished is printed, and no process
  the hunt started is left running

### Requirement: Nothing a round starts outlives it
Stopping a round SHALL stop every process the round started, including a child whose own parent has already exited.
On Windows this SHALL also hold when the hunt itself is killed. A round that runs past its timeout SHALL be stopped
and reported as hung, with its output so far.

#### Scenario: An orphaned grandchild
- **WHEN** a round's test starts a child, which starts a grandchild and exits, and the round is then stopped
- **THEN** the grandchild is no longer running

#### Scenario: A hung round
- **WHEN** a round runs past the round timeout
- **THEN** it is stopped, reported as hung with its output so far, and the hunt carries on with the next round

#### Scenario: The hunt is killed on Windows
- **WHEN** the hunt's own process is terminated on Windows while a round runs
- **THEN** the round and everything it started end with it

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
A number of workers (other than `auto`), rounds or load that isn't a whole number, is below its minimum (1 worker, 1 round, 0 load) or
asks for more load than the CPUs the hunt may use (its affinity, or a container's limit) SHALL be refused before
anything runs, with an error naming the option, the value and what is allowed.

#### Scenario: Workers chosen for the machine
- **WHEN** the hunt is given `--workers auto` on a machine that lets it use 8 CPUs
- **THEN** it runs 6 workers without load, and 4 with a load of 2: three quarters of the CPUs, rounded down, less
  the load, and at least 1

#### Scenario: Too much load
- **WHEN** the hunt is asked for more load than the CPUs it may use
- **THEN** it runs nothing and exits with an error naming the load, the value and the number of CPUs it may use

#### Scenario: Zero rounds
- **WHEN** the hunt is asked for 0 rounds
- **THEN** it runs nothing and exits with an error naming the rounds option and its minimum

### Requirement: The hunt runs on every platform
The hunt SHALL run on Linux, macOS and Windows with the same options and output. How to run it on each, including
Linux in Docker as an ordinary user with an init process that reaps orphans, and each supported Python version in an
environment of its own, SHALL be documented.

#### Scenario: Text the console can't show
- **WHEN** a failure's message or traceback holds characters the console's encoding can't represent, as on a
  Windows console using a legacy code page
- **THEN** the summary still prints, showing those characters escaped, and the JSON results hold them unchanged

#### Scenario: A second Python version
- **WHEN** someone follows the documented steps to hunt on Python 3.13 after hunting on 3.12
- **THEN** the hunt runs on 3.13, and the 3.12 environment they develop in is left as it was

#### Scenario: Linux in Docker
- **WHEN** someone follows the documented steps for Linux
- **THEN** the hunt runs in a container as a user other than root, with an init process as PID 1, on a copy of the
  repository inside the container

### Requirement: The agreed campaign runs from one command
`scripts/flake_campaign.py` SHALL run, one hunt at a time, the campaign #100 agreed: every supported Python version,
each without load and with load, run directly and, when asked, in the Linux container. It SHALL take the versions
from the supported range (python-support), and SHALL refuse to start, naming the problem, if that range is
malformed.

#### Scenario: The versions are the supported ones
- **WHEN** the campaign runs while the supported range is 3.12 and 3.13
- **THEN** it runs hunts on exactly 3.12 and 3.13, each in that version's own environment, and leaves `.venv` as it
  was

#### Scenario: Directly and in Docker
- **WHEN** the campaign runs with Docker asked for
- **THEN** it runs every direct hunt, then builds the Linux image for each Python version from the committed tree and
  runs the same hunts in it

#### Scenario: Uncommitted changes with Docker
- **WHEN** Docker is asked for and the working tree has uncommitted changes
- **THEN** the campaign refuses to start, naming the changed files, because the container would hunt the commit
  while the direct hunts hunted the working tree

### Requirement: The campaign's selection is the OS-sensitive tests, named in one place
By default the campaign SHALL hunt the tests that depend on time, processes, signals or file watching, named as path
patterns in one place, and SHALL be able to hunt the whole suite instead. Each pattern SHALL match at least one test
file, checked by a test.

#### Scenario: A new platform test file
- **WHEN** a new `packages/troupe/tests/test_platform_*.py` file is added
- **THEN** the campaign hunts it without any change to the campaign

### Requirement: The campaign reports every hunt together
When the campaign ends, however it ends, it SHALL write one report, as Markdown ready for #100 and as JSON. For
each hunt (Python version, load, direct or Docker) the report SHALL say whether it ran clean, which tests failed with
their runs and failures, and the first failure's message, and SHALL name the commit, the machine and the options. A
campaign in which any hunt failed or didn't run SHALL exit non-zero.

#### Scenario: One hunt finds a flake
- **WHEN** one of eight hunts reports a test failing in 2 of 30 runs
- **THEN** the report lists all eight hunts, seven clean, and names that test with 2 of 30 under the hunt that found
  it, with its first message

#### Scenario: Stopped part-way
- **WHEN** the person presses Ctrl-C during the third hunt
- **THEN** the campaign stops that hunt, runs no more, and writes the report of the hunts that ran, marking the third
  as stopped
