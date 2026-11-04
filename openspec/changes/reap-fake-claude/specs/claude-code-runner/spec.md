# Spec Delta

## ADDED Requirements

### Requirement: The runner's tests stop it as troupe would
A test that starts the Claude Code runner SHALL end it the way troupe ends a runner: the runner starts in a process
group (or the platform's equivalent) of its own, and the test's teardown kills that whole group, so the stand-in
`claude` the runner started ends with it, on Linux, macOS and Windows.

#### Scenario: A test ends while the stand-in hangs
- **WHEN** a test starts a run whose stand-in `claude` hangs, sends a second `run/start`, and ends without
  cancelling the run
- **THEN** after the test's teardown neither the runner nor the stand-in is running

### Requirement: A runner test that leaves its stand-in running fails
When a test of the runner process ends, its teardown SHALL kill the runner and then check that the stand-in `claude`
it started, as named by the pid the stand-in recorded, has ended within a named limit. A stand-in still running SHALL
fail the test, naming the stand-in's pid and the run's workspace.

#### Scenario: A runner killed without its stand-in
- **WHEN** a test's teardown kills its runner in a way that leaves the stand-in running
- **THEN** the test fails at teardown, naming the stand-in's pid and the run's workspace

#### Scenario: A stand-in that ended with its runner
- **WHEN** a test's stand-in `claude` has ended by the time its runner has been killed
- **THEN** the test's teardown passes
