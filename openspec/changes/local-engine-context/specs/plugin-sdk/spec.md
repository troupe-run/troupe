## ADDED Requirements

### Requirement: The SDK parses the runtime's engine
The SDK SHALL parse `run/start`'s `runtime.engine` into its run-start type when present, and leave it absent when
the field is. A value outside the protocol's set of engines SHALL be a protocol error naming `runtime.engine` and the
values it takes. The SDK's set SHALL be the schema's.

#### Scenario: An engine in run start
- **WHEN** the SDK parses a `run/start` whose `runtime.engine` is `lm-studio`
- **THEN** the parsed runtime's engine is `lm-studio`

#### Scenario: No engine
- **WHEN** the SDK parses a `run/start` whose runtime has no `engine`
- **THEN** the parsed runtime has no engine

#### Scenario: An engine the protocol doesn't name
- **WHEN** the SDK parses a `run/start` whose `runtime.engine` is `vllm`
- **THEN** it raises a protocol error naming `runtime.engine` and the engines it takes

#### Scenario: The engine list matches the schema
- **WHEN** an engine is added to `runtime.schema.json`'s set and not to the SDK's
- **THEN** the SDK's tests fail, naming the engine
