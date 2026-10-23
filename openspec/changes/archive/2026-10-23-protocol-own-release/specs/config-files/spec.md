## MODIFIED Requirements

### Requirement: Each config file names its schema twice
Each YAML config file SHALL begin with a `# yaml-language-server: $schema=<url>` comment and a `$schema: <url>`
key, both naming its kind's schema at troupe.run by the major version of the protocol troupe carries.

#### Scenario: An actor file names its schema
- **WHEN** an actor file is written by a troupe that carries protocol 0.2.0
- **THEN** its first line is the language-server comment and its first key is `$schema`, both naming
  `https://troupe.run/protocol/0/config/actor.schema.json`

#### Scenario: A protocol past 1.0
- **WHEN** an actor file is written by a troupe that carries protocol 1.3.0
- **THEN** both name `https://troupe.run/protocol/1/config/actor.schema.json`

#### Scenario: The file validates against its schema
- **WHEN** a written actor file is validated against the actor schema troupe carries
- **THEN** it is valid
