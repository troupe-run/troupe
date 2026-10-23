## MODIFIED Requirements

### Requirement: Version reporting
`troupe --version` SHALL print the installed troupe version and the protocol version it carries to standard output
and exit 0, without needing a theatre, an identity or a running daemon.

#### Scenario: Version outside any theatre
- **WHEN** a user runs `troupe --version` in a directory with no `.troupe/`
- **THEN** standard output contains the installed version string
- **AND** the exit code is 0

#### Scenario: The protocol version
- **WHEN** a user runs `troupe --version` with a troupe that carries protocol 0.2.0
- **THEN** standard output names `protocol 0.2.0` after troupe's own version
