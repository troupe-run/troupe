# Spec Delta

## MODIFIED Requirements

### Requirement: A script is a list of steps played in order
The runner SHALL take its script from the `run/start` options, inline or as a path to a JSON file, and play its
steps in order. The steps SHALL cover: send a run event, send a transcript record, write to standard error, wait,
write a file in the workspace, hang, exit with a code, and write a raw line to standard output. The runner SHALL play
consecutive steps that don't wait one after another without reading troupe's messages in between, and SHALL answer
what troupe sent at a `wait`, at a `hang`, during a replay's delays, and once the script ends. A script's steps
therefore play the same way whenever troupe's messages arrive.

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
