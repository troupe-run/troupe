# Spec Delta

## MODIFIED Requirements

### Requirement: A script's steps cover what a runner can send or do
The steps SHALL cover: send a run event, send a transcript record, write to standard error, wait, write a file in the
workspace, carry out a tool call, hang, exit with a code, and write a raw line to standard output.

#### Scenario: The options schema defines each step
- **WHEN** the scripted runner's published options schema is read
- **THEN** it defines a step for each of a run event, a transcript record, standard error, a wait, a file write, a
  tool call, a hang, an exit and a raw standard output line

## ADDED Requirements

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
