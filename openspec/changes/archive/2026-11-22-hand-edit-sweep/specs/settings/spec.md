## MODIFIED Requirements

### Requirement: The environment is a settings source
A setting SHALL be settable from the environment variable `TROUPE_SETTING_` followed by the setting's name in
capitals. A boolean setting SHALL accept exactly `true` or `false`. An unset or empty variable SHALL count as absent.
Settings SHALL be read from the sources of the session that called the core, never from a request.

#### Scenario: Set from the environment
- **WHEN** `TROUPE_SETTING_MARK_MERGES_RESOLVED` is `true`
- **THEN** `mark_merges_resolved` is true, and its source is `env`

#### Scenario: Empty counts as unset
- **WHEN** `TROUPE_SETTING_MARK_MERGES_RESOLVED` is the empty string
- **THEN** `mark_merges_resolved` is false, and its source is `default`

#### Scenario: A request can't set one
- **WHEN** a `sync` request is checked against its schema
- **THEN** the schema has no field that sets a setting

### Requirement: A malformed setting is an error
A setting's value that is present but isn't one the setting accepts SHALL fail the command with
`settings.invalid-value`, naming the variable, the value and the accepted values. It SHALL NOT fall through to the
default.

#### Scenario: A typo
- **WHEN** `TROUPE_SETTING_MARK_MERGES_RESOLVED` is `yes` and a person runs `troupe sync`
- **THEN** the command fails with `settings.invalid-value`, naming the variable, `yes`, `true` and `false`
- **AND** nothing is written and git's index is unchanged
