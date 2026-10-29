# releases Specification

## Purpose

Capability: `cap:development`

How troupe's packages get their versions, changelogs and releases: all derived from the Conventional Commits on
`main` through a release pull request, never edited by hand.

## Requirements

### Requirement: Versions and changelogs come from the commit history
A package's version and changelog SHALL change only through a release pull request, which is opened and updated
automatically from the Conventional Commits on `main` that touch the package. A commit that touches no package
paths SHALL change no version.

#### Scenario: A releasable commit lands
- **WHEN** a `feat` or `fix` commit that changes files under `packages/troupe/` lands on `main`
- **THEN** a release pull request is opened, or updated if one is open, with the bumped version and a changelog
  entry for that commit

#### Scenario: A commit outside every package
- **WHEN** a commit that changes only `openspec/` or `scripts/` lands on `main`
- **THEN** no package's version or changelog changes because of it

### Requirement: Pre-1.0 versioning
While a package's major version is 0, a breaking change SHALL bump its minor version, and a `feat` or `fix` SHALL
bump at most its minor version. The first release of every package SHALL be 0.1.0.

#### Scenario: Breaking change before 1.0
- **WHEN** a package at 0.3.2 has a released commit marked breaking (`!` or a `BREAKING CHANGE:` footer)
- **THEN** its next version is 0.4.0

#### Scenario: First release
- **WHEN** the first release pull request is merged
- **THEN** every package it releases is at version 0.1.0

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

### Requirement: Each plugin has its own version
Each package under `plugins/` SHALL have its own version and release, unaffected by changes to other packages.

#### Scenario: Only core changed
- **WHEN** the only releasable commits since the last release change `packages/`
- **THEN** the release pull request doesn't change any plugin's version

### Requirement: Every package has its own changelog
Each package SHALL have a `CHANGELOG.md` in its own directory, listing the released commits that touched it, under
the version that released them.

#### Scenario: Changelog location
- **WHEN** a release pull request releases `troupe-runner-scripted`
- **THEN** it updates `plugins/runner-scripted/CHANGELOG.md`

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

### Requirement: The release pull request keeps the lock file in step
A release pull request SHALL update each released package's version in `uv.lock` together with its
`pyproject.toml`, so the lock file stays consistent with the workspace.

#### Scenario: Lock file after a version bump
- **WHEN** CI runs on a release pull request
- **THEN** `uv sync --locked` succeeds

### Requirement: The release pull request passes every required check
The release pull request SHALL be opened by the release App, whose pull requests trigger CI. Every commit on it
SHALL be authored by the release App's bot account, and SHALL be a Conventional Commit with a DCO sign-off. The
required checks then run and pass, with no exemption apart from the release-branch exemption granted in
`development-workflow`.

#### Scenario: Required checks on the release pull request
- **WHEN** a release pull request is opened or updated
- **THEN** the CI, DCO and guard checks all run on it

#### Scenario: A commit on the release branch by anyone else
- **WHEN** the release branch carries a commit authored by anyone other than the release App's bot account
- **THEN** the guard check fails on the release pull request

### Requirement: Merging the release pull request publishes the release
When a release pull request is merged into `main`, a tag `<package>-v<version>` and a GitHub release SHALL be
created for each package it released, with that version's changelog section as the release notes.

#### Scenario: Release after merge
- **WHEN** a release pull request that releases `troupe` at 0.1.0 is merged
- **THEN** the tag `troupe-v0.1.0` and a GitHub release for it exist

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
