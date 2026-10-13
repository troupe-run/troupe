# Spec Delta

## MODIFIED Requirements

### Requirement: Errors are rendered from structured data
Every error SHALL originate as structured data with a problem, an optional path, and a fix. The CLI SHALL render it
to standard error, write nothing to standard output, and exit non-zero. The structured shape SHALL be defined once,
in the language-neutral protocol, so other surfaces can render the same error their own way.

#### Scenario: An error names the problem and the fix
- **WHEN** a command fails
- **THEN** standard error contains the problem and the fix
- **AND** it contains the path when the error concerns a file or directory
- **AND** standard output is empty
- **AND** the exit code is non-zero

#### Scenario: Error data matches the protocol schema
- **WHEN** any error the CLI can produce is serialised as data
- **THEN** it validates against the protocol's error schema, including the details schema for its code
