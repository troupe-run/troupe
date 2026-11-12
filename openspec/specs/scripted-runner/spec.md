# scripted-runner Specification

## Purpose

Capability: `cap:actor-runners`

A deterministic actor runner for tests: it plays a script or replays a recorded stream through the runner
contract, so every run outcome can be produced on demand, offline and for free.

## Requirements

### Requirement: The scripted runner is a self-contained plugin
The scripted runner SHALL be an out-of-process plugin with its own package definition and tests, SHALL speak only
the runner contract, using the plugin SDK's types for it, and SHALL NOT import troupe. The import rule SHALL be
enforced by a check that fails the build.

#### Scenario: Plugin imports troupe
- **WHEN** code under `plugins/` imports `troupe`
- **THEN** the import contract check fails

#### Scenario: The scripted runner's event types
- **WHEN** the scripted runner plays an event step, answers `initialize` or refuses a request
- **THEN** it uses the plugin SDK's event type, protocol versions and error codes, and defines no copy of its own

#### Scenario: A deliberate violation still plays
- **WHEN** a script overrides an event's `seq` to skip a number, or writes a raw line
- **THEN** the runner sends it as the script says, as before

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
workspace, carry out a tool call, hang, exit with a code, and write a raw line to standard output.

#### Scenario: The options schema defines each step
- **WHEN** the scripted runner's published options schema is read
- **THEN** it defines a step for each of a run event, a transcript record, standard error, a wait, a file write, a
  tool call, a hang, an exit and a raw standard output line

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

### Requirement: A tool step runs a call through the SDK's tools
A `tool` step SHALL name a tool, its input and, optionally, a call id, and SHALL carry the call out with the SDK's
tools, for the run's workspace, effects and scratch directory, as a model's call would be. The runner SHALL send the
SDK's `tool_call` and `tool_result` events for it, numbered as its other events, and its `init` SHALL report
`effects` as `checked`.

#### Scenario: A declared write through a tool step
- **WHEN** an actor declares `write` for `out/**` and expects `out/a.txt`, and its script writes it with a `tool` step
- **THEN** the run succeeds, with its effect check and audit passed

#### Scenario: A read-only actor's write is refused
- **WHEN** an actor declares no effects and its script has a `tool` step calling `Write` on `out/a.txt`, expecting an
  error, then sends `ok`
- **THEN** the run sends a `tool_result` with `isError` true naming the `write` effect, no `out/a.txt` exists, and
  the run succeeds

### Requirement: A tool step can expect an error
A `tool` step MAY say whether its result must be an error. A result that doesn't match SHALL end the run with an
error result naming the step.

#### Scenario: A result that wasn't expected
- **WHEN** a `tool` step calling `Delete` expects success and the call is refused
- **THEN** the run ends with an error result naming the step and the refusal

### Requirement: A write step is still a raw write
A `write` step SHALL write its file without any effect checking it, so tests can show what the audit catches.

#### Scenario: A raw write outside the declaration
- **WHEN** an actor declares no effects and its script uses a `write` step for `out/a.txt` and sends `ok`
- **THEN** the run's audit fails, naming `out/a.txt`

### Requirement: The scripted runner takes an optional runtime
The scripted runner SHALL accept a `run/start` with or without a `runtime`, and SHALL use it only in the steps that
check or echo it.

#### Scenario: A run with a runtime and no runtime steps
- **WHEN** the scripted runner receives a `run/start` with a `runtime`, and a script with no runtime steps
- **THEN** it plays the script as it would without one

### Requirement: A script can check the runtime it received
A script SHALL be able to hold a step that checks `run/start`'s runtime: its name, endpoint, model and price, and the
`sha256:` hash of the credential in `TROUPE_RUNTIME_CREDENTIAL`, or that there's no runtime, no price or no
credential. When the check fails, the runner SHALL end the run with an error result naming each field that differs,
giving a hash in place of the credential, and play no later step.

#### Scenario: The runtime matches
- **WHEN** a script checks for the runtime `openai`, its endpoint, the model `gpt-test` and a credential's hash, and
  troupe started the run with exactly those
- **THEN** the runner plays the script's next step

#### Scenario: The model differs
- **WHEN** a script checks for the model `gpt-a` and `run/start` carries `gpt-b`
- **THEN** the run ends with an error result naming `model`, `gpt-a` and `gpt-b`, and no later step is played

#### Scenario: The credential differs
- **WHEN** a script checks for one credential's hash and the environment holds another
- **THEN** the run ends with an error result naming both hashes, and no part of either value

#### Scenario: The price differs
- **WHEN** a script checks for no price and `run/start`'s runtime carries one
- **THEN** the run ends with an error result naming `price`, and no later step is played

### Requirement: A script can echo the credential
A script SHALL be able to hold a step that sends the credential from `TROUPE_RUNTIME_CREDENTIAL`, unchanged, in a
`log` event, a transcript record and its standard error, standing in for a runner that leaks it, so a test can show
what troupe keeps. With no credential, the step SHALL end the run with an error result.

#### Scenario: Echoing the key
- **WHEN** a script with the echo step is played in a run whose environment holds a credential
- **THEN** the runner sends the credential in a `log` event, a transcript record and its standard error

### Requirement: A script's result can carry an estimated cost
A script's result step SHALL be able to carry `estimatedCostUsd`, sent as given whether or not `run/start` carried a
price, so troupe's tests can produce both an estimate and one troupe gave no price for.

#### Scenario: An estimate with no price
- **WHEN** a script's result step carries `estimatedCostUsd` 0.5 and `run/start` carries no price
- **THEN** the runner sends a `result` with `estimatedCostUsd` 0.5

### Requirement: The scripted runner can use transcript kinds
Started with `--transcript-kinds`, the runner SHALL accept `transcript-kinds` when troupe offers it; otherwise it
SHALL accept no capability. A transcript step SHALL take an optional `kind`, sent as the step gives it, whether or not
the run uses kinds, so a script can break the contract's rule on purpose.

#### Scenario: Started with the flag
- **WHEN** the runner is started with `--transcript-kinds` and troupe offers `transcript-kinds`
- **THEN** its `initialize` answer names `transcript-kinds`

#### Scenario: Started without the flag
- **WHEN** the runner is started without `--transcript-kinds` and troupe offers `transcript-kinds`
- **THEN** its `initialize` answer names no capability

#### Scenario: A step with a kind
- **WHEN** a script's transcript step is `{"record": "data: {}", "kind": "received"}`
- **THEN** the runner sends that record with kind `received`

#### Scenario: A kind the contract doesn't define
- **WHEN** a script's transcript step has kind `request`
- **THEN** `run/start` is refused with `scripted.invalid-script`, naming the step's kind

### Requirement: A script's error result names its reason
A script's `event` step that sends an `error` result SHALL name its reason, so tests can drive every reason on the
list. The scripted runner's own failures SHALL carry a reason too: a cancel honoured with a result `cancelled`, and a
check a step makes that fails (the character, the runtime, the credential, a tool step's expected error) `other`.

#### Scenario: A scripted error result
- **WHEN** a script's `event` step sends a `result` with status `error` and `reason` `quota`
- **THEN** the runner sends that `result`, with `reason` `quota`

#### Scenario: A scripted error result without a reason
- **WHEN** a script's `event` step sends a `result` with status `error` and no `reason`
- **THEN** the script doesn't validate against the scripted runner's options schema, and the run is refused before it
  starts with `scripted.invalid-script`, naming `reason`

#### Scenario: A cancel honoured with a result
- **WHEN** a script sets the cancel behaviour to honour with a result, and the host cancels the run
- **THEN** the runner's `result` has status `error` and `reason` `cancelled`

#### Scenario: A character check that fails
- **WHEN** a script's character check finds a character it didn't expect
- **THEN** the runner's `result` has status `error` and `reason` `other`, and its message names both characters

### Requirement: A script's error result can say it wasn't retried
A script's `event` step that sends an `error` result SHALL be able to name `notRetried`, so tests can drive it. The scripted runner's
options schema SHALL hold it to the contract's rule, so a script that names it on an `ok` result or beside a reason a
`retry` can't name is refused before the run starts.

#### Scenario: A scripted result that wasn't retried
- **WHEN** a script's `event` step sends a `result` with status `error`, `reason` `network` and `notRetried`
  `side-effect`
- **THEN** the runner sends that `result`, with `notRetried` `side-effect`

#### Scenario: A scripted notRetried beside the wrong reason
- **WHEN** a script's `event` step sends a `result` with status `error`, `reason` `quota` and `notRetried`
  `side-effect`
- **THEN** the run is refused before it starts with `scripted.invalid-script`, naming `notRetried`
