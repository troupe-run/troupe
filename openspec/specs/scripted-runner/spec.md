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
steps in order.

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

#### Scenario: Steps after a result play before shutdown is answered
- **WHEN** a script sends `init` and an ok `result`, then exits with code 3, and troupe's `shutdown` reaches the
  runner before the exit step
- **THEN** the runner exits with code 3, without answering `shutdown`

#### Scenario: A message waits for the next step that waits
- **WHEN** troupe sends `run/cancel` while the runner plays a run of steps that don't wait, followed by a `hang`
- **THEN** every one of those steps is played, and the cancel is answered at the `hang`

### Requirement: A script's steps cover what a runner can send or do
The steps SHALL cover: send a run event, send a transcript record, write to standard error, wait, write a file in the
workspace, hang, exit with a code, and write a raw line to standard output.

#### Scenario: The options schema defines each step
- **WHEN** the scripted runner's published options schema is read
- **THEN** it defines a step for each of a run event, a transcript record, standard error, a wait, a file write, a
  hang, an exit and a raw standard output line

### Requirement: Steps that don't wait play without reading troupe's messages
The runner SHALL play consecutive steps that don't wait one after another without reading troupe's messages in
between, and SHALL answer what troupe sent at a `wait`, at a `hang`, during a replay's delays, and once the script
ends. A script's steps therefore play the same way whenever troupe's messages arrive.

#### Scenario: A message is answered during a wait
- **WHEN** troupe sends `run/cancel` while the runner is at a `wait` step, with cancel ignored
- **THEN** the runner answers the cancel before the wait ends, and plays the steps after it

#### Scenario: A message is answered during a replay's delays
- **WHEN** troupe sends `run/cancel` while the runner replays a recording with its delays, with cancel ignored
- **THEN** the runner answers the cancel before the replay ends, and sends every recorded event

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

### Requirement: The scripted runner exits on end of input
The scripted runner SHALL stop playing and exit when its standard input closes, including while hanging.

#### Scenario: Input closes during a hang
- **WHEN** the runner is hanging and its standard input is closed
- **THEN** the runner exits

### Requirement: The scripted runner publishes its schemas
The scripted runner SHALL publish, inside its own plugin, a JSON Schema for its options (an inline script or a
script path, and the replay options, including every step a script can hold) and one for its own error codes and
their details. Its tests SHALL validate every script and recording it ships against the options schema.

#### Scenario: Shipped scripts validate
- **WHEN** each script and recording in the plugin's fixtures and tests is checked
- **THEN** it validates against the scripted runner's options schema

#### Scenario: A step the schema doesn't define
- **WHEN** a script holds a step type, or a step field, that the runner doesn't define
- **THEN** it doesn't validate against the options schema, and the runner refuses it with `scripted.invalid-script`

#### Scenario: The runner's own errors validate
- **WHEN** the scripted runner answers with one of its own error codes
- **THEN** the error validates against the contract's error schema together with the runner's published error
  codes

### Requirement: A script can check the character it received
A script SHALL be able to hold a step that checks the character in `run/start` against a `sha256:` hash, or checks
that there is none. When the check fails, the runner SHALL end the run with an error result naming the hash it
expected and the hash it received, and play no later step.

#### Scenario: The character matches
- **WHEN** a script checks for the hash of "You are the tester." and `run/start` carries that character
- **THEN** the runner plays the script's next step

#### Scenario: The character differs
- **WHEN** a script checks for one hash and `run/start` carries a different character, or none
- **THEN** the run ends with an error result naming both hashes, and no later step is played

### Requirement: The scripted runner's schemas are installed with it
The scripted runner's published schemas SHALL be installed with the plugin, so troupe can find its options schema
from the installed plugin, without starting the runner.

#### Scenario: The options schema from an installed plugin
- **WHEN** troupe checks an actor's options for the scripted runner
- **THEN** it reads the options schema from the installed plugin, and the runner isn't started
