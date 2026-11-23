## MODIFIED Requirements

### Requirement: Config and sync commands
The CLI SHALL offer `troupe config set`, `troupe config unset`, `troupe config get`, `troupe config drop`, `troupe
config keep` and `troupe sync`, each calling the core through the client protocol. `troupe config get` SHALL take
`--json`, which writes the query's result exactly in its protocol shape. There SHALL be no `troupe flush`.

#### Scenario: Config get as JSON
- **WHEN** a person runs `troupe config get --json`
- **THEN** standard output is one JSON document that validates against the `config-get` result schema

#### Scenario: Flush is gone
- **WHEN** a person runs `troupe flush`
- **THEN** it is refused as an unknown command

#### Scenario: Dropping an abandoned edit
- **WHEN** a person runs `troupe config drop <change>` for a droppable abandoned edit
- **THEN** it prints the changes it dropped and the event files it removed, and exits 0

#### Scenario: Keeping an abandoned edit
- **WHEN** a person runs `troupe config keep <change>`
- **THEN** it says the changes are kept and troupe won't ask about them again, and exits 0
