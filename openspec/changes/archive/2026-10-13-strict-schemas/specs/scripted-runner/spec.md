# Spec Delta

## ADDED Requirements

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
