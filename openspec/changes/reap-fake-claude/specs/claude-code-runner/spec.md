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

### Requirement: A test that leaves a stand-in running fails
After each test, a check SHALL confirm that every stand-in `claude` started during it has ended, waiting no longer
than a named limit. A stand-in still running then SHALL be stopped and the test SHALL fail, naming the stand-in's
pid and working directory. The check SHALL stop only a process it knows is still that stand-in, never another
process that has taken its pid. It SHALL cover the plugin's tests and core's tests that use the stand-in.

#### Scenario: A test leaves a hanging stand-in behind
- **WHEN** a test starts a stand-in `claude` that hangs and ends without stopping it
- **THEN** the test fails at teardown naming the stand-in's pid and working directory, and the stand-in is no longer
  running

#### Scenario: A stand-in escapes before it has started up
- **WHEN** a stand-in `claude` outside its runner's process group or job records itself only after its test's check
- **THEN** a later test's check in the same test process fails naming the stand-in's working directory and stops it,
  or, after the last test, the end of the run stops it

#### Scenario: A test whose stand-in has ended
- **WHEN** a test's stand-in `claude` has exited, or been stopped by the runner, before the test ends
- **THEN** the check passes and stops nothing

#### Scenario: A stand-in's pid is taken by another process
- **WHEN** a stand-in has ended and another process now has its pid
- **THEN** the check passes and doesn't signal that process
