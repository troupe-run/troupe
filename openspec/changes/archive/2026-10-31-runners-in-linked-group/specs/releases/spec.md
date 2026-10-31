# Spec Delta

## RENAMED Requirements

- FROM: `### Requirement: Core and its bundled adapters share one version`
- TO: `### Requirement: The bundle and everything it ships share one version`

## MODIFIED Requirements

### Requirement: The bundle and everything it ships share one version
Every package under `packages/`, and every workspace member the bundle `troupe-run` depends on, SHALL belong to one
linked group: when any of them releases, all of them release at the same version, so the bundle's release is the
latest of everything it ships. The protocol under `protocol/` SHALL NOT belong to it.

#### Scenario: Only one adapter changed
- **WHEN** the only releasable commit since the last release changes `packages/troupe-store-text/`
- **THEN** the release pull request gives every package in the linked group the same new version

#### Scenario: Only a runner changed
- **WHEN** the only releasable commit since the last release is a `fix:` that changes `plugins/runner-scripted/`
- **THEN** the release pull request gives every package in the linked group, `troupe-run` included, the same new
  version
- **AND** merging it creates a `troupe-run-v<version>` tag at that version

#### Scenario: A protocol change
- **WHEN** a `feat!` commit changes only `protocol/README.md`
- **THEN** the release pull request bumps the protocol's version and lists the commit in `protocol/CHANGELOG.md`
- **AND** it changes no version in the linked group

### Requirement: Every workspace member is configured for release
Every workspace member SHALL appear in the release configuration and the version manifest, and each package under
`packages/` or shipped by the bundle SHALL be in the linked group. A missing member SHALL fail the repository's check,
naming the member and the file to add it to. For an entry missing from the version manifest, member or protocol, the
fix SHALL be the version of its latest `<component>-v*` tag, or `0.0.0` only if it has none, never a guess.

#### Scenario: A new package without release config
- **WHEN** a package is added under `packages/` but not to the release configuration
- **THEN** `scripts/check.py` fails, naming the package and the configuration file

#### Scenario: A bundled runner left out of the linked group
- **WHEN** `troupe-run` depends on `troupe-runner-scripted` and it isn't in the linked group's components
- **THEN** `scripts/check.py` fails, naming `troupe-runner-scripted`, that `troupe-run` ships it, the configuration
  file and the fix

#### Scenario: A component the bundle doesn't ship in the linked group
- **WHEN** the linked group's components list a package that is neither under `packages/` nor a dependency of
  `troupe-run`
- **THEN** `scripts/check.py` fails, naming the package, the configuration file and the fix

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

## REMOVED Requirements

### Requirement: Each plugin has its own version
**Reason**: The bundle is the only way to install a runner, so a runner versioned apart from it gives users nothing,
and a runner-only release made no bundle tag (#214, owner, 2026-10-31). Bundled plugins now release with the linked
group.
**Migration**: None needed: nothing has released yet. A plugin that moves to its own repository (#38, #67) leaves the
bundle's dependencies and the linked group in that change, and versions on its own there.
