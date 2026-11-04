# Spec Delta

## ADDED Requirements

### Requirement: Run start carries the run's runtime
When an actor names a runtime, `run/start` SHALL carry `runtime`: its `name`, `endpoint` and `model` as troupe
resolved them, and `credential`, `true` when the runner's environment holds the credential and `false` when the
runtime has none. It SHALL NOT carry the credential's value or its variable's name. Without a runtime it is absent.

#### Scenario: A runtime with a credential
- **WHEN** troupe starts a run on the runtime `openai` with the model `gpt-test`
- **THEN** `run/start` carries `runtime` with `name` `openai`, the endpoint, `model` `gpt-test` and `credential`
  `true`, and nothing else

#### Scenario: No runtime
- **WHEN** troupe starts a run for an actor that names no runtime
- **THEN** `run/start` has no `runtime` field, rather than a null

#### Scenario: The value isn't in run start
- **WHEN** a `run/start` with a `runtime` is validated against the contract's schema
- **THEN** the schema has no field for a credential's value or its variable's name

### Requirement: The credential's value is in the runner's environment as TROUPE_RUNTIME_CREDENTIAL
When `run/start`'s `runtime.credential` is `true`, the runner's environment SHALL hold the credential's value as
`TROUPE_RUNTIME_CREDENTIAL`, and SHALL NOT hold it otherwise. The runner SHALL send it only to the runtime's endpoint,
and SHALL NOT put it in a run event, a transcript record, its standard error or an error.

#### Scenario: The runner finds the key
- **WHEN** troupe starts a run whose `runtime.credential` is `true`
- **THEN** the runner's environment holds `TROUPE_RUNTIME_CREDENTIAL`, and not the variable the runtime's config names

#### Scenario: No credential
- **WHEN** troupe starts a run on `ollama`
- **THEN** the runner's environment has no `TROUPE_RUNTIME_CREDENTIAL`

## MODIFIED Requirements

### Requirement: The runner takes direction, character and configuration only from its run start
The runner SHALL use no other source of direction, character or configuration from troupe than the `run/start`
request, apart from the runtime's credential, which it SHALL take only from its environment.

#### Scenario: Nothing reaches the runner outside its run start
- **WHEN** troupe starts a runner for an actor with a character, with a direction and runner-specific options
- **THEN** neither the runner's command line nor its environment holds the direction, the character or any of the
  options' values

#### Scenario: The credential is the one exception
- **WHEN** troupe starts a runner for an actor on a runtime with a credential
- **THEN** its environment holds `TROUPE_RUNTIME_CREDENTIAL`, and its command line holds no part of the runtime

### Requirement: The native transcript is a separate stream
The runner SHALL send its engine's native output, record by record and unchanged, as `run/transcript`
notifications in the order produced. Transcript records SHALL NOT be interpreted by the host, apart from masking the
run's credential (spec: runs).

#### Scenario: Native records are kept verbatim
- **WHEN** a runner sends transcript records, in a run with no credential or whose records don't hold it
- **THEN** the stored transcript contains exactly those records, in that order, byte for byte

#### Scenario: A record that holds the credential
- **WHEN** a runner sends a transcript record that holds the run's credential
- **THEN** the stored record is the same bytes with the credential masked
