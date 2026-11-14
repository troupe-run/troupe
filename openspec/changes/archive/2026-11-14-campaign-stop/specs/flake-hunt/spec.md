## MODIFIED Requirements

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

#### Scenario: The interrupt lands at any moment
- **WHEN** the person presses Ctrl-C while the campaign waits on a hunt, at whatever point of that wait it lands,
  and the hunt then exits
- **THEN** the campaign sees the hunt's exit, reports it as stopped and exits, within its own stop limit, and never
  waits on a hunt that has already exited
