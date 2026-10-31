## ADDED Requirements

### Requirement: A stuck test names itself in the check's output
When a single test has run longer than the stall limit, the tests gate SHALL write the stack of every thread in that
test's process to the check's output, including the test's own frame, so the output names the test. This SHALL hold
when the tests run in parallel, and in CI on Linux, macOS and Windows. The dump SHALL NOT end the test or change
whether the gate passes.

#### Scenario: A test stuck in a parallel run
- **WHEN** the check runs the tests in parallel and one test runs past the stall limit
- **THEN** the check's output holds a stack dump whose frames name that test's file and function, written while the
  test is still running

#### Scenario: A slow test that finishes
- **WHEN** a test runs past the stall limit and then passes
- **THEN** its stack dump is in the output, and the test and the gate still pass

#### Scenario: No test stalls
- **WHEN** every test finishes within the stall limit
- **THEN** the output holds no stack dump

#### Scenario: A CI job that stalls
- **WHEN** a test stalls in a CI job on any platform
- **THEN** the job's log names the test before the job's timeout stops it

### Requirement: The stall limit is set in one place
The stall limit SHALL be a named setting in the repository's pytest configuration, which every test run reads,
including runs the check starts and the flake hunt's rounds unless the hunt is given a limit of its own. It SHALL be
below the CI job's timeout by more than the time the suite takes, and above the slowest test's normal duration.

#### Scenario: The flake hunt without a limit of its own
- **WHEN** the flake hunt runs without `--stall`
- **THEN** its rounds dump a stuck test's stack at the limit the pytest configuration sets

#### Scenario: The flake hunt with a limit of its own
- **WHEN** the flake hunt runs with `--stall 60`
- **THEN** its rounds dump a stuck test's stack at 60 seconds
