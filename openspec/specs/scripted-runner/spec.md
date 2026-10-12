# scripted-runner Specification

## Purpose

A deterministic actor runner for tests: it plays a script or replays a recorded stream through the runner
contract, so every run outcome can be produced on demand, offline and for free.

## Requirements

### Requirement: The scripted runner is a self-contained plugin
The scripted runner SHALL be an out-of-process plugin with its own package definition and tests, SHALL speak only
the runner contract, and SHALL NOT import troupe. The import rule SHALL be enforced by a check that fails the build.

#### Scenario: Plugin imports troupe
- **WHEN** code under `plugins/` imports `troupe`
- **THEN** the import contract check fails

### Requirement: A script is a list of steps played in order
The runner SHALL take its script from the `run/start` options, inline or as a path to a JSON file, and play its
steps in order. The steps SHALL cover: send a run event, send a transcript record, write to standard error, wait,
write a file in the workspace, hang, exit with a code, and write a raw line to standard output.

#### Scenario: Script plays in order
- **WHEN** a script sends `init`, a `tool_call`, a `tool_result` and a `result`
- **THEN** the host receives those events in that order with `seq` 0 to 3

#### Scenario: Script from a file
- **WHEN** the options name a script file
- **THEN** the runner plays that file's steps

#### Scenario: Invalid script
- **WHEN** the script is malformed, names an unknown step, or a step has a field the step doesn't define
- **THEN** the runner answers `run/start` with an error naming the step and the problem, and plays nothing

#### Scenario: Unknown option
- **WHEN** the `run/start` options hold a key other than the script, the script path and the replay options
- **THEN** the runner answers with an error naming the key and plays nothing

### Requirement: The runner numbers events itself
The runner SHALL assign `seq` and the run id to every event it sends, so scripts do not repeat them, unless a step
deliberately overrides them to produce a protocol violation.

#### Scenario: Deliberate sequence gap
- **WHEN** a step overrides `seq` to skip a number
- **THEN** the runner sends the event with that `seq`

### Requirement: Every outcome can be produced on demand
Scripts SHALL be able to produce each outcome the host can derive: success, an error result, an error flagged
under a "success" label, retries including authentication retries, a hang, a cancel that is honoured, a cancel
that is ignored, a stream that ends without a `result`, a crash, and a protocol violation.

#### Scenario: Cancel ignored
- **WHEN** a script sets the cancel behaviour to ignore and then hangs
- **THEN** the runner acknowledges `run/cancel` but keeps running until it is killed

#### Scenario: Cancel honoured without a result
- **WHEN** a script sets the cancel behaviour to exit without a result
- **THEN** on `run/cancel` the runner exits without sending a `result`

#### Scenario: Crash
- **WHEN** a script's exit step runs before any `result`
- **THEN** the runner exits with the given code without sending a `result`

### Requirement: Recorded streams replay verbatim
The runner SHALL replay a recording, a JSON Lines file of run events and transcript records, sending each in order
unchanged except for the run id. Delays between records SHALL be replayed only when the options ask for it.

#### Scenario: Replay of a recording
- **WHEN** a recording is replayed
- **THEN** the host receives the recorded events and transcript records in the recorded order

### Requirement: Fixtures pair real engine output with protocol events
The plugin SHALL include fixtures captured from real Claude Code runs: each pairs the native stream-json records,
unchanged except for scrubbing, with the protocol events they map to. The fixtures SHALL include `is_error` under a
"success" subtype, authentication retries, a run terminated without a `result`, and a successful run with tool calls.
Each fixture SHALL record its provenance.

#### Scenario: Fixtures replay through the contract
- **WHEN** each fixture is replayed by the scripted runner
- **THEN** every message validates against the contract and the host derives the outcome the fixture states

#### Scenario: Provenance is recorded
- **WHEN** a fixture is read
- **THEN** it names the Claude Code version, the date, the command used and the scrubbing applied

### Requirement: Fixtures hold no secrets
No committed fixture SHALL contain a credential, a token, a host user name or a host path outside the run's
workspace. A test SHALL check every fixture for the known patterns.

#### Scenario: Secret pattern in a fixture
- **WHEN** a fixture contains a string matching a credential pattern or the capturing host's home path
- **THEN** the fixture check fails and names the fixture and line

### Requirement: The scripted runner exits on end of input
The scripted runner SHALL stop playing and exit when its standard input closes, including while hanging.

#### Scenario: Input closes during a hang
- **WHEN** the runner is hanging and its standard input is closed
- **THEN** the runner exits
