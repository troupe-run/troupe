## ADDED Requirements

### Requirement: Policy decides whether actors may compact
The policy setting `compaction` SHALL take `actors` (the default: each actor's `onContextFull` decides), `all` (every
actor compacts unless its own `onContextFull` is `fail`), or `none` (no actor compacts). It SHALL be read through
the policy seam with its source, from `TROUPE_POLICY_COMPACTION`.

#### Scenario: The default
- **WHEN** `compaction` is read and no source sets it
- **THEN** its value is `actors`, and its source is `default`

#### Scenario: Set from the environment
- **WHEN** `TROUPE_POLICY_COMPACTION` is `all`
- **THEN** `compaction` is `all`, and its source is `env`

#### Scenario: A value that isn't one of the three
- **WHEN** `TROUPE_POLICY_COMPACTION` is `yes`
- **THEN** the command fails with `policy.invalid-value`, naming the variable, `yes`, `actors`, `all` and `none`
- **AND** nothing runs and nothing is recorded
