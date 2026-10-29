# Spec Delta

## MODIFIED Requirements

### Requirement: Every workspace member is configured for release
Every workspace member SHALL appear in the release configuration and the version manifest, and each package under
`packages/` SHALL be in the linked group. A missing member SHALL fail the repository's check, and the failure
SHALL name the member and the file to add it to. For an entry missing from the version manifest, member or protocol,
the fix SHALL be the version of its latest `<component>-v*` tag, or `0.0.0` only if it has none, never a guess.

#### Scenario: A new package without release config
- **WHEN** a package is added under `packages/` but not to the release configuration
- **THEN** `scripts/check.py` fails, naming the package and the configuration file

#### Scenario: The protocol put back in the linked group
- **WHEN** `protocol` is listed in the linked group's components
- **THEN** `scripts/check.py` fails, naming the protocol, the configuration file and the fix

#### Scenario: A released member lost from the manifest
- **WHEN** `plugins/runner-scripted` has released and its entry is removed from `.release-please-manifest.json`
- **THEN** `scripts/check.py` fails, naming the member, the manifest file and its tags, `troupe-runner-scripted-v*`
- **AND** the message doesn't suggest `0.0.0` as the fix, only as the version when no such tag exists

#### Scenario: The protocol lost from the manifest
- **WHEN** the protocol's entry is removed from `.release-please-manifest.json`
- **THEN** `scripts/check.py` fails, naming the protocol, the manifest file and its tags, `protocol-v*`
- **AND** the message doesn't suggest `0.0.0` as the fix, only as the version when no such tag exists
