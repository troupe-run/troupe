# Spec Delta

## ADDED Requirements

### Requirement: troupe carries the schemas it was built with
The troupe package SHALL carry a copy of every schema in `protocol/schemas/`, and core SHALL read schemas only from
that copy and from installed plugins' published schemas. Core SHALL NOT fetch a schema over the network. The quality
check SHALL fail when the copy differs from `protocol/schemas/`.

#### Scenario: A schema changed without its copy
- **WHEN** a schema in `protocol/schemas/` changes and the package's copy isn't regenerated
- **THEN** `scripts/check.py` fails, naming the schema and the command that regenerates the copy

#### Scenario: An installed troupe
- **WHEN** troupe is installed from a built wheel, with no checkout of this repository
- **THEN** it finds every schema it needs, by `$id`, without a network connection

### Requirement: A plugin's published schemas are installed with it
Each plugin's published schemas SHALL be installed with the plugin, so troupe can read them without starting the
plugin, and without importing it.

#### Scenario: A runner's options schema
- **WHEN** troupe checks an actor's options for the scripted runner
- **THEN** it reads the options schema the installed scripted runner publishes, and the runner isn't started
