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

### Requirement: Every package has its own changelog
Each package SHALL have a `CHANGELOG.md` in its own directory, listing the released commits that touched it, under
the version that released them.

#### Scenario: Changelog location
- **WHEN** a release pull request releases `troupe-runner-scripted`
- **THEN** it updates `plugins/runner-scripted/CHANGELOG.md`

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

### Requirement: Only releasing commits appear in changelogs
A changelog SHALL list `feat`, `fix`, `perf` and `revert` commits, and breaking changes of any type. Commits of
other types SHALL NOT appear in any changelog and SHALL NOT release a component on their own. A breaking change of
any type SHALL be listed under breaking changes and release its component.

#### Scenario: A docs commit under a package
- **WHEN** the only commit since the last release is a `docs` commit that changes `packages/troupe/README.md`
- **THEN** no release pull request releases `troupe`, and no changelog lists the commit

#### Scenario: A docs commit beside a feature
- **WHEN** a `feat` commit and a `docs` commit both change `packages/troupe/` since the last release
- **THEN** troupe's changelog lists the `feat` commit and has no Documentation section

#### Scenario: A breaking change of a hidden type
- **WHEN** a `refactor!` commit changes `packages/troupe-store-text/`
- **THEN** the release pull request lists it under breaking changes in troupe-store-text's changelog and releases
  the linked group

#### Scenario: A performance fix
- **WHEN** a `perf` commit changes `packages/troupe-vcs-git/`
- **THEN** troupe-vcs-git's changelog lists it under Performance Improvements

### Requirement: The release pull request reads the history since the last release
release-please SHALL read `main` back to the last release, up to 1000 commits, in pages of 100 commits, so a first
release lists every commit on `main` that's shown in a changelog. Pages of 100 are a mitigation, recorded in #223: a
rebase-merged pull request whose commits fall on two pages can still put its last commit under every component the
pull request changed.

#### Scenario: The first release reaches the oldest commits
- **WHEN** the release pull request for 0.1.0 is built from a `main` of fewer than 1000 commits
- **THEN** troupe's changelog lists `74cbf20` (`feat(cli): add --version, flags anywhere, the -- rule and
  structured errors`)

#### Scenario: A rebase-merged pull request within one page
- **WHEN** a pull request with a `feat` commit changing `plugins/runner-scripted/` and a `docs` commit changing only
  `openspec/` is merged by rebase, and both commits are in one page of history
- **THEN** only runner-scripted's changelog lists the `feat` commit, and no changelog lists the `docs` commit

### Requirement: The history and changelog settings are checked
The release configuration SHALL set, at its top level, the page size (100), the search depth (1000) and the
changelog sections. The repository's check SHALL fail when any of them is missing or has another value, or when a
component's entry sets its own changelog sections, naming the configuration file, the setting and the fix.

#### Scenario: The page size removed
- **WHEN** the release configuration doesn't set `commit-batch-size`
- **THEN** `scripts/check.py` fails, naming the configuration file, `commit-batch-size` and that it must be 100

#### Scenario: A smaller search depth
- **WHEN** the release configuration sets `commit-search-depth` to 500
- **THEN** `scripts/check.py` fails, naming the configuration file, the value 500 and that it must be 1000

#### Scenario: Documentation shown again
- **WHEN** the release configuration's `changelog-sections` shows `docs`
- **THEN** `scripts/check.py` fails, naming the configuration file, `changelog-sections` and the sections it must
  be

#### Scenario: A component with its own sections
- **WHEN** the protocol's entry in the release configuration sets `changelog-sections`
- **THEN** `scripts/check.py` fails, naming the protocol, the configuration file and the fix, to remove it from the
  entry
