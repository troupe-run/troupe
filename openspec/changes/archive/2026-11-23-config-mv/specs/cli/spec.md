## MODIFIED Requirements

### Requirement: Config and sync commands
The CLI SHALL offer `troupe config set`, `troupe config unset`, `troupe config mv`, `troupe config get` and `troupe
sync`, each calling the core through the client protocol. `troupe config get` SHALL take `--json`, which writes the
query's result exactly in its protocol shape. There SHALL be no `troupe flush`.

#### Scenario: Config get as JSON
- **WHEN** a person runs `troupe config get --json`
- **THEN** standard output is one JSON document that validates against the `config-get` result schema

#### Scenario: Flush is gone
- **WHEN** a person runs `troupe flush`
- **THEN** it is refused as an unknown command

#### Scenario: Config mv
- **WHEN** a person runs `troupe config mv actors.tester actors.qa`
- **THEN** standard output says `tester` was renamed `qa`, with the change id and the files written and removed

#### Scenario: Config mv takes two paths
- **WHEN** a person runs `troupe config mv actors.tester`
- **THEN** it is refused as a usage error, saying `config mv` takes the old name and the new one

## ADDED Requirements

### Requirement: Status and logs show an actor's current name
When a run's actor has been renamed since the run, `troupe status` and `troupe logs` SHALL show the name it ran under
followed by its current name, as `tester (now qa)`, following a chain of renames to the current name: status in the
run's actor column or line, and logs in an `actor:` line after the run's outcome. A run's recorded actor SHALL NOT
change.

#### Scenario: A run before a rename
- **WHEN** a run of `tester` is recorded, then `tester` is renamed `qa`, and a person runs `troupe status`
- **THEN** the run's line shows `tester (now qa)`

#### Scenario: A chain of renames
- **WHEN** a run of `tester` is recorded, then `tester` is renamed `qa` and `qa` renamed `checker`, and a person runs
  `troupe logs` on the run
- **THEN** it shows `actor: tester (now checker)`

#### Scenario: An actor that wasn't renamed
- **WHEN** a run's actor has its name still
- **THEN** status shows the name alone, and logs adds no `actor:` line

#### Scenario: An actor removed since
- **WHEN** a run's actor has been removed since, with no rename
- **THEN** status shows the name alone, and logs adds no `actor:` line

### Requirement: Perform names the new name of a renamed actor
`troupe perform` on a name config no longer holds because it was renamed SHALL be refused as for any unknown actor,
and its fix SHALL name the actor's current name.

#### Scenario: Performing the old name
- **WHEN** `tester` has been renamed `qa`, and a person runs `troupe perform tester`
- **THEN** it is refused as an unknown actor, and the fix says `tester` was renamed `qa`
