## MODIFIED Requirements

### Requirement: Core and its bundled adapters share one version
Every package under `packages/` SHALL belong to one linked group: when any of them releases, all of them release at
the same version. The protocol under `protocol/` SHALL NOT belong to it.

#### Scenario: Only one adapter changed
- **WHEN** the only releasable commit since the last release changes `packages/troupe-store-text/`
- **THEN** the release pull request gives every package under `packages/` the same new version

#### Scenario: A protocol change
- **WHEN** a `feat!` commit changes only `protocol/README.md`
- **THEN** the release pull request bumps the protocol's version and lists the commit in `protocol/CHANGELOG.md`
- **AND** it changes no version under `packages/`

### Requirement: Every workspace member is configured for release
Every workspace member SHALL appear in the release configuration and the version manifest, and each package under
`packages/` SHALL be in the linked group. A missing member SHALL fail the repository's check, and the failure
SHALL name the member and the file to add it to.

#### Scenario: A new package without release config
- **WHEN** a package is added under `packages/` but not to the release configuration
- **THEN** `scripts/check.py` fails, naming the package and the configuration file

#### Scenario: The protocol put back in the linked group
- **WHEN** `protocol` is listed in the linked group's components
- **THEN** `scripts/check.py` fails, naming the protocol, the configuration file and the fix

## ADDED Requirements

### Requirement: The protocol has its own version
The protocol SHALL be released on its own: only when a releasable commit changes files under `protocol/`, at its own
version, under the same pre-1.0 rules as every package, tagged `protocol-v<version>`, with its own changelog.

#### Scenario: Only core changed
- **WHEN** the only releasable commits since the last release change `packages/troupe/src/troupe/cli/`
- **THEN** the release pull request doesn't change the protocol's version

#### Scenario: A schema changed
- **WHEN** a `feat` commit changes a schema in `protocol/schemas/` and the troupe package's copy of it
- **THEN** the release pull request releases the protocol and the linked group, each at its own next version

#### Scenario: Protocol release tag
- **WHEN** a release pull request that releases the protocol at 0.2.0 is merged
- **THEN** the tag `protocol-v0.2.0` and a GitHub release for it exist

### Requirement: A protocol release updates the version troupe records
A release pull request that releases the protocol SHALL set the protocol version the troupe package records to the
new version, in the same pull request. The repository's check SHALL fail when the recorded version differs from the
manifest's protocol version, or when the protocol's release configuration doesn't update it, naming the file and fix.

#### Scenario: The release pull request
- **WHEN** a release pull request bumps the protocol from 0.1.0 to 0.2.0
- **THEN** it also changes the version the troupe package records from 0.1.0 to 0.2.0
- **AND** `scripts/check.py` passes on it

#### Scenario: A recorded version edited by hand
- **WHEN** the version the troupe package records differs from the protocol's version in the manifest
- **THEN** `scripts/check.py` fails, naming both files and both versions

#### Scenario: The update left out of the release configuration
- **WHEN** the protocol's entry in the release configuration doesn't update the recorded version
- **THEN** `scripts/check.py` fails, naming the entry and the update to add
