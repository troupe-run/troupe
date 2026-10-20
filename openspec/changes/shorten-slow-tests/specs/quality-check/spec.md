## ADDED Requirements

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
