# Spec Delta

## ADDED Requirements

### Requirement: Init with an audition warms its runner's engine
After `troupe init --audition` records the audition, when the runner troupe knows has a warm-up, init SHALL say it
has started, run it once, bounded by a named limit, and report how it went as a notice: warmed up, failed with the
runner's problem and fix, or cut off at the limit. A rehearsal SHALL NOT run it.

#### Scenario: A runner whose engine warms up
- **WHEN** a person runs `troupe init --audition --runner mistralrs` on macOS
- **THEN** init first sends `runner.warming-up`, and its notices include `runner.warmed-up`, naming the runner and how
  long it took

#### Scenario: A runner that can't run here
- **WHEN** the runner's warm-up reports the `mistralrs.unsupported-python` error
- **THEN** init succeeds, and its notices include `runner.warm-up-failed` with the runner's problem and fix

#### Scenario: A warm-up past its limit
- **WHEN** the warm-up takes longer than `RUNNER_WARM_UP_TIMEOUT_SECONDS`
- **THEN** it's stopped, and the notice `runner.warm-up-cut-off` says the first run finishes it

#### Scenario: A rehearsal
- **WHEN** a person runs `troupe init --audition --runner mistralrs --rehearse`
- **THEN** no warm-up runs
