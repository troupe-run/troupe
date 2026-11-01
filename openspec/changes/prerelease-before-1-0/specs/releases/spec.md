# Spec Delta

## ADDED Requirements

### Requirement: Releases before 1.0 are pre-releases
A GitHub release for a component version whose major is 0 SHALL be created as a pre-release. A release at 1.0 or
later SHALL NOT be, unless its version carries a pre-release suffix. The setting SHALL NOT change the release pull
request, and a pre-release SHALL start the release install check like any other published release.

#### Scenario: The first release
- **WHEN** the release pull request that releases the linked group and the protocol at 0.1.0 is merged
- **THEN** every GitHub release it creates, `troupe-run-v0.1.0` and `protocol-v0.1.0` included, is marked
  Pre-release
- **AND** none of them is marked Latest

#### Scenario: A component reaches 1.0
- **WHEN** a release pull request that releases the linked group at 1.0.0 is merged
- **THEN** its GitHub releases aren't marked Pre-release

#### Scenario: The install check runs for a pre-release
- **WHEN** the `troupe-run-v0.1.0` pre-release is published
- **THEN** the release install check runs against `troupe-run-v0.1.0`

### Requirement: The pre-release setting is checked
The release configuration SHALL set pre-releases once for every component. The repository's check SHALL fail when
it isn't set to true, or when a component's own entry sets it, naming the configuration file and the fix.

#### Scenario: The setting removed
- **WHEN** the release configuration doesn't set `prerelease` at the top level
- **THEN** `scripts/check.py` fails, naming the configuration file and that `prerelease` must be `true`

#### Scenario: The setting not true
- **WHEN** the release configuration's top-level `prerelease` is `false`, or the string `"true"`
- **THEN** `scripts/check.py` fails, naming the configuration file, the value and that it must be `true`

#### Scenario: A component overriding it
- **WHEN** the protocol's entry in the release configuration sets `prerelease`
- **THEN** `scripts/check.py` fails, naming the protocol, the configuration file and the fix, to remove it from the
  entry
