## ADDED Requirements

### Requirement: A second initialize is refused
A runner SHALL answer an `initialize` that comes after a handshake it answered successfully with the contract error
`runner.already-initialized`. The first handshake's answer SHALL stand: the protocol version and the capabilities it
named stay those of the run. An `initialize` after one the runner refused (an unsupported version) is not a second
handshake.

#### Scenario: A second initialize offering different capabilities
- **WHEN** the host sends `initialize` offering `transcript-kinds`, the runner accepts it, the host sends `run/start`
  and then a second `initialize` offering no capabilities
- **THEN** the runner answers the second with an error whose code is `runner.already-initialized`
- **AND** the run's transcript records carry a kind, as the first handshake agreed

#### Scenario: A second initialize before run/start
- **WHEN** the host sends `initialize` twice before `run/start`
- **THEN** the second is refused with `runner.already-initialized`, and a `run/start` after it starts the run

#### Scenario: Initialize again after an unsupported version
- **WHEN** a runner refuses an `initialize` offering only versions it doesn't support, and the host then sends one
  offering a version it does
- **THEN** the runner answers the second `initialize` with the handshake

### Requirement: A message's strings are Unicode text
Every string in a runner's message, keys included, SHALL be Unicode text: it SHALL NOT hold a lone surrogate, even
though JSON can escape one (`\ud800`). A runner with bytes that aren't text SHALL send them as a `base64` transcript
record. The host SHALL treat a lone surrogate as a protocol violation (spec: actor-runners).

#### Scenario: A transcript record holding a lone surrogate
- **WHEN** a runner sends a `run/transcript` record whose JSON string is `"a\ud800b"`
- **THEN** it is a protocol violation

#### Scenario: Bytes that aren't text
- **WHEN** a runner has a record whose bytes aren't UTF-8
- **THEN** it sends that record with encoding `base64`

#### Scenario: An engine's lone surrogate
- **WHEN** a bundled runner's engine sends JSON whose string holds an escaped lone surrogate (`"x\ud800y"`), in an
  answer or an error
- **THEN** each string the runner sends from it holds U+FFFD in its place, and the run carries on to its result
- **AND** before the first event holding U+FFFD (just after `init`, for one in or before `init`) the runner sends a
  `context` event of kind `other`, by `runner`, whose message names where the text was and how many characters were
  replaced

## MODIFIED Requirements

### Requirement: Failures use the shared error shape
A JSON-RPC error from a runner SHALL carry, in its `data`, an object that validates against the protocol's error
schema (code, problem, fix, and optionally path and details). Its code SHALL be one of the contract's own error
codes, or one the runner publishes with its details schema.

#### Scenario: Invalid run start
- **WHEN** a runner rejects `run/start` because it is invalid
- **THEN** the error's `data` validates against the protocol's error schema and names what was invalid

#### Scenario: A contract error code
- **WHEN** a runner refuses a request it can't parse, an unknown method, an unsupported version, a second
  `initialize`, a second `run/start` or invalid params
- **THEN** the error's code is the contract's code for that failure, and its details match that code's schema

#### Scenario: A code the runner didn't publish
- **WHEN** a runner's error carries a code that is neither the contract's nor in the runner's published error
  codes
- **THEN** it does not validate against the contract's schema together with the runner's
