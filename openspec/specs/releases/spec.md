# releases Specification

## Purpose

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
Every package under `packages/`, and the protocol under `protocol/`, SHALL belong to one linked group: when any of
them releases, all of them release at the same version.

#### Scenario: Only one adapter changed
- **WHEN** the only releasable commit since the last release changes `packages/troupe-store-text/`
- **THEN** the release pull request gives every package under `packages/` the same new version

#### Scenario: A protocol change
- **WHEN** a `feat!` commit changes only files under `protocol/`
- **THEN** the release pull request bumps the linked group's version and lists the commit in
  `protocol/CHANGELOG.md`

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
SHALL name the member and the file to add it to.

#### Scenario: A new package without release config
- **WHEN** a package is added under `packages/` but not to the release configuration
- **THEN** `scripts/check.py` fails, naming the package and the configuration file

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
