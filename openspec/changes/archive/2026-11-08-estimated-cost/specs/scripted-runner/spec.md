## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: A script's result can carry an estimated cost
A script's result step SHALL be able to carry `estimatedCostUsd`, sent as given whether or not `run/start` carried a
price, so troupe's tests can produce both an estimate and one troupe gave no price for.

#### Scenario: An estimate with no price
- **WHEN** a script's result step carries `estimatedCostUsd` 0.5 and `run/start` carries no price
- **THEN** the runner sends a `result` with `estimatedCostUsd` 0.5
