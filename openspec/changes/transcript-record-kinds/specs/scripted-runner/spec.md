# Spec Delta

## ADDED Requirements

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
- **THEN** `run/start` is refused with `runner.invalid-params`, naming the step's kind
