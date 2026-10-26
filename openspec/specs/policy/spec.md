# policy Specification

## Purpose

Capability: `cap:policy`

Gives troupe one seam through which every policy setting is read, each with a named default and a known source, so
policy can grow levels and combinators later without anything else reading policy its own way.

## Requirements

### Requirement: Policy is read through one seam
Every policy setting SHALL be read only through troupe's policy seam, which SHALL return the setting's value together
with the source it came from. Each setting SHALL have its default in one named place.

#### Scenario: The default and its source
- **WHEN** `allow_unenforced_local_stage` is read and no source sets it
- **THEN** its value is false, and its source is `default`

### Requirement: The environment is a policy source
A policy setting SHALL be settable from the environment variable `TROUPE_POLICY_` followed by the setting's name in
capitals. A boolean setting SHALL accept exactly `true` or `false`. An unset or empty variable SHALL count as absent.

#### Scenario: Set from the environment
- **WHEN** `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE` is `true`
- **THEN** `allow_unenforced_local_stage` is true, and its source is `env`

#### Scenario: Empty counts as unset
- **WHEN** `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE` is the empty string
- **THEN** `allow_unenforced_local_stage` is false, and its source is `default`

### Requirement: A malformed policy value is an error
A policy value that is present but isn't one the setting accepts SHALL fail the command with `policy.invalid-value`,
naming the variable, the value and the accepted values. It SHALL NOT fall through to the default.

#### Scenario: A typo
- **WHEN** `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE` is `yes`
- **THEN** the command fails with `policy.invalid-value`, naming the variable, `yes`, `true` and `false`
- **AND** nothing runs and nothing is recorded

### Requirement: Policy never comes from a request
No command or query request SHALL carry a policy value. Policy SHALL be read from the sources of the session that
called the core.

#### Scenario: A request can't allow an unenforced run
- **WHEN** a `perform` request is checked against its schema
- **THEN** the schema has no field that sets a policy value
