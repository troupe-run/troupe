# Spec Delta

## MODIFIED Requirements

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
