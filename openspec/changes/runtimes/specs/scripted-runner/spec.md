# Spec Delta

## ADDED Requirements

### Requirement: The scripted runner takes an optional runtime
The scripted runner SHALL accept a `run/start` with or without a `runtime`, and SHALL use it only in the steps that
check or echo it.

#### Scenario: A run with a runtime and no runtime steps
- **WHEN** the scripted runner receives a `run/start` with a `runtime`, and a script with no runtime steps
- **THEN** it plays the script as it would without one

### Requirement: A script can check the runtime it received
A script SHALL be able to hold a step that checks `run/start`'s runtime: its name, endpoint and model, and the
`sha256:` hash of the credential in `TROUPE_RUNTIME_CREDENTIAL`, or that there's no runtime or no credential. When
the check fails, the runner SHALL end the run with an error result naming each field that differs, giving a hash in
place of the credential, and play no later step.

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

### Requirement: A script can echo the credential
A script SHALL be able to hold a step that sends the credential from `TROUPE_RUNTIME_CREDENTIAL`, unchanged, in a
`log` event, a transcript record and its standard error, standing in for a runner that leaks it, so a test can show
what troupe keeps. With no credential, the step SHALL end the run with an error result.

#### Scenario: Echoing the key
- **WHEN** a script with the echo step is played in a run whose environment holds a credential
- **THEN** the runner sends the credential in a `log` event, a transcript record and its standard error
